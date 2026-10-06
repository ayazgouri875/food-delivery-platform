from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.events import EventType, publish_order_event
from app.core.metrics import ORDERS_CREATED_TOTAL, ORDER_REVENUE_PAISE_TOTAL
from app.core.redis import delete_cache, distributed_lock, get_cache, set_cache
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db
from app.models.address import Address
from app.models.cart import Cart, CartItem
from app.models.menu import MenuItem
from app.models.order import Order, OrderItem, OrderStatus, OrderStatusHistory
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.order import (
    OrderCreate,
    OrderDetailResponse,
    OrderResponse,
    OrderStatusUpdate,
)
from app.services.notifications import NotificationService

router = APIRouter(prefix="/orders", tags=["Orders"])

# Valid state transitions for the Order Finite State Machine
VALID_TRANSITIONS = {
    OrderStatus.CREATED: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
    OrderStatus.CONFIRMED: [OrderStatus.PREPARING, OrderStatus.CANCELLED],
    OrderStatus.PREPARING: [OrderStatus.READY_FOR_PICKUP],
    OrderStatus.READY_FOR_PICKUP: [OrderStatus.PICKED_UP, OrderStatus.CANCELLED],
    OrderStatus.PICKED_UP: [OrderStatus.DELIVERED],
    OrderStatus.DELIVERED: [],
    OrderStatus.CANCELLED: [],
}


@router.post(
    "/",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Checkout cart and place an order (uses Redis Distributed Lock & Row-Level Locking)"
)
def place_order(
    order_in: OrderCreate,
    background_tasks: BackgroundTasks,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Checkout the customer's cart with production-grade concurrency controls:
    1. Distributed Lock (Redis): Serializes checkout requests per-user to eliminate
       double-tap race conditions on the mutable cart.
    2. Distributed Idempotency: Deduplicates identical requests via Redis key + DB column,
       replaying the existing order if already completed.
    3. Deadlock-Free Row-Level Locking: Acquires SELECT FOR UPDATE locks on menu items
       in strictly ascending item_id order (Dijkstra's resource hierarchy).
    4. Price & Address Snapshotting: Freezes unit prices and delivery address in order record.
    5. Atomic Inventory Decrement & Cart Invalidation in a single DB transaction.
    """
    idempotency_key = order_in.idempotency_key or x_idempotency_key
    idempotency_cache_key = f"idempotency:order:{current_user.id}:{idempotency_key}" if idempotency_key else None

    # Step A: Fast-path Idempotency Check (Redis cache & DB fallback)
    if idempotency_cache_key:
        cached = get_cache(idempotency_cache_key)
        if cached:
            if cached.get("status") == "COMPLETED":
                existing_order = db.query(Order).filter(Order.id == cached.get("order_id")).first()
                if existing_order:
                    return existing_order
            elif cached.get("status") == "PROCESSING":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An identical order checkout request is currently being processed. Please wait."
                )

        # Check PostgreSQL persistent storage in case Redis cache expired
        existing_db_order = db.query(Order).filter(
            Order.user_id == current_user.id,
            Order.idempotency_key == idempotency_key
        ).first()
        if existing_db_order:
            set_cache(idempotency_cache_key, {"status": "COMPLETED", "order_id": existing_db_order.id}, ttl=86400)
            return existing_db_order

    # Step B: Acquire Per-User Distributed Lock to serialize concurrent checkout attempts
    user_lock_key = f"lock:checkout:user:{current_user.id}"
    try:
        with distributed_lock(user_lock_key, lock_timeout_seconds=15, acquire_timeout_seconds=5.0):
            # Double-check idempotency under lock to catch concurrent in-flight requests that just completed
            if idempotency_cache_key:
                cached = get_cache(idempotency_cache_key)
                if cached and cached.get("status") == "COMPLETED":
                    existing_order = db.query(Order).filter(Order.id == cached.get("order_id")).first()
                    if existing_order:
                        return existing_order

                # Mark as PROCESSING with short 30-second TTL
                set_cache(idempotency_cache_key, {"status": "PROCESSING"}, ttl=30)

            try:
                # 1. Fetch user's cart
                cart = db.query(Cart).filter(Cart.user_id == current_user.id).first()
                if not cart or not cart.items:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Your cart is empty. Add items before checking out."
                    )

                # 2. Fetch and format delivery address snapshot
                address = db.query(Address).filter(
                    Address.id == order_in.delivery_address_id,
                    Address.user_id == current_user.id
                ).first()
                if not address:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Delivery address not found."
                    )
                address_snapshot = f"{address.title}: {address.address_line}, {address.city} - {address.postal_code or ''}".strip()

                # 3. Validate restaurant status
                restaurant = db.query(Restaurant).filter(Restaurant.id == cart.restaurant_id).first()
                if not restaurant or not restaurant.is_active or not restaurant.is_open:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Restaurant is currently closed or unavailable."
                    )

                # 4. Inventory check and Deadlock-Free Row-Level Locking (SELECT FOR UPDATE)
                subtotal = 0
                order_items_to_create = []

                # Crucial Concurrency Strategy: Sort cart items deterministically by item_id
                # to guarantee global lock ordering and eliminate database deadlocks.
                sorted_cart_items = sorted(cart.items, key=lambda ci: ci.item_id)

                for cart_item in sorted_cart_items:
                    # Lock this menu_item row for update to prevent concurrent overselling
                    menu_item = (
                        db.query(MenuItem)
                        .filter(MenuItem.id == cart_item.item_id)
                        .with_for_update()
                        .first()
                    )

                    if not menu_item or not menu_item.is_available:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"'{cart_item.item.name}' is no longer available."
                        )

                    # Check stock if inventory tracking is enabled (stock_count != -1)
                    if menu_item.stock_count != -1:
                        if menu_item.stock_count < cart_item.quantity:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Insufficient stock for '{menu_item.name}'. Only {menu_item.stock_count} portions left."
                            )
                        # Decrement stock atomically
                        menu_item.stock_count -= cart_item.quantity

                    item_subtotal = menu_item.price * cart_item.quantity
                    subtotal += item_subtotal

                    # Snapshot item details
                    order_items_to_create.append({
                        "item_id": menu_item.id,
                        "item_name": menu_item.name,
                        "unit_price": menu_item.price,
                        "quantity": cart_item.quantity,
                        "subtotal": item_subtotal
                    })

                delivery_fee = 4000  # Flat ₹40.00
                grand_total = subtotal + delivery_fee

                # 5. Create Order
                new_order = Order(
                    user_id=current_user.id,
                    restaurant_id=restaurant.id,
                    delivery_address_id=address.id,
                    delivery_address_snapshot=address_snapshot,
                    status=OrderStatus.CREATED,
                    subtotal=subtotal,
                    delivery_fee=delivery_fee,
                    grand_total=grand_total,
                    idempotency_key=idempotency_key
                )
                db.add(new_order)
                db.flush()

                # Create OrderItems with snapshot values
                for item_data in order_items_to_create:
                    order_item = OrderItem(
                        order_id=new_order.id,
                        item_id=item_data["item_id"],
                        item_name=item_data["item_name"],
                        unit_price=item_data["unit_price"],
                        quantity=item_data["quantity"],
                        subtotal=item_data["subtotal"]
                    )
                    db.add(order_item)

                # Record initial state in history
                history_entry = OrderStatusHistory(
                    order_id=new_order.id,
                    old_status=None,
                    new_status=OrderStatus.CREATED.value,
                    changed_by_user_id=current_user.id,
                    notes=order_in.notes or "Order placed from cart"
                )
                db.add(history_entry)

                # 6. Clear customer's cart
                db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
                cart.restaurant_id = None

                db.commit()
                db.refresh(new_order)

                # Step C: Save idempotency cache on success (24 hour TTL)
                if idempotency_cache_key:
                    set_cache(idempotency_cache_key, {"status": "COMPLETED", "order_id": new_order.id}, ttl=86400)

                # Step D: Real-Time Event & Asynchronous Notification
                publish_order_event(
                    order_id=new_order.id,
                    event_type=EventType.ORDER_CREATED,
                    data={
                        "order_id": new_order.id,
                        "status": new_order.status.value,
                        "grand_total": new_order.grand_total,
                        "restaurant_id": new_order.restaurant_id
                    }
                )
                background_tasks.add_task(
                    NotificationService.send_order_placed,
                    new_order.id,
                    current_user.id,
                    current_user.email,
                    new_order.grand_total
                )

                # Record Prometheus Business Metrics
                ORDERS_CREATED_TOTAL.inc()
                ORDER_REVENUE_PAISE_TOTAL.inc(new_order.grand_total)

                return new_order

            except Exception:
                db.rollback()
                # Clear PROCESSING status if an error occurred so client can retry cleanly
                if idempotency_cache_key:
                    delete_cache(idempotency_cache_key)
                raise

    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another checkout operation is currently processing for your account. Please wait."
        )


@router.get(
    "/",
    response_model=List[OrderResponse],
    summary="List orders for current user or restaurant owner"
)
def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Order)

    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Order.user_id == current_user.id)
    elif current_user.role == UserRole.RESTAURANT:
        # Show orders for restaurants owned by this user
        owned_restaurants = db.query(Restaurant.id).filter(Restaurant.owner_id == current_user.id).subquery()
        query = query.filter(Order.restaurant_id.in_(owned_restaurants))
    # ADMIN sees all orders

    return query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()


@router.get(
    "/{order_id}",
    response_model=OrderDetailResponse,
    summary="Get order details with complete status timeline"
)
def get_order_detail(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    # Authorize access
    if current_user.role == UserRole.CUSTOMER and order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if current_user.role == UserRole.RESTAURANT:
        restaurant = db.query(Restaurant).filter(Restaurant.id == order.restaurant_id).first()
        if not restaurant or restaurant.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return order


@router.patch(
    "/{order_id}/status",
    response_model=OrderDetailResponse,
    summary="Transition order status (FSM state machine)"
)
def update_order_status(
    order_id: int,
    status_in: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    old_status = order.status
    new_status = status_in.status

    # Validate state transition rules
    allowed_transitions = VALID_TRANSITIONS.get(old_status, [])
    if new_status not in allowed_transitions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Illegal transition: Cannot change order from {old_status} to {new_status}. Allowed: {allowed_transitions}"
        )

    # Role-based transition authorization
    if current_user.role == UserRole.RESTAURANT:
        restaurant = db.query(Restaurant).filter(Restaurant.id == order.restaurant_id).first()
        if not restaurant or restaurant.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this restaurant")
        if new_status not in [OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP, OrderStatus.CANCELLED]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurants cannot transition to this state")

    # Apply transition
    order.status = new_status

    # Record status change history audit trail
    history = OrderStatusHistory(
        order_id=order.id,
        old_status=old_status.value,
        new_status=new_status.value,
        changed_by_user_id=current_user.id,
        notes=status_in.notes
    )
    db.add(history)
    db.commit()
    db.refresh(order)

    # Real-Time Event Broadcast to WebSockets
    publish_order_event(
        order_id=order.id,
        event_type=f"ORDER_{new_status.value}",
        data={
            "order_id": order.id,
            "old_status": old_status.value,
            "new_status": new_status.value,
            "notes": status_in.notes
        }
    )

    return order


@router.post(
    "/{order_id}/cancel",
    response_model=OrderDetailResponse,
    summary="Cancel order and restore inventory if applicable"
)
def cancel_order(
    order_id: int,
    notes: str = Query("Order cancelled by customer", description="Cancellation reason"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if current_user.role != UserRole.ADMIN and order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to cancel this order")

    # Business rule: Orders already PREPARING or beyond cannot be cancelled by customer
    if order.status not in [OrderStatus.CREATED, OrderStatus.CONFIRMED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order cannot be cancelled at stage '{order.status}'. Food is already being prepared or dispatched."
        )

    old_status = order.status
    order.status = OrderStatus.CANCELLED

    # Restore inventory
    for item in order.items:
        if item.item_id:
            menu_item = db.query(MenuItem).filter(MenuItem.id == item.item_id).first()
            if menu_item and menu_item.stock_count != -1:
                menu_item.stock_count += item.quantity

    # Record history
    history = OrderStatusHistory(
        order_id=order.id,
        old_status=old_status.value,
        new_status=OrderStatus.CANCELLED.value,
        changed_by_user_id=current_user.id,
        notes=notes
    )
    db.add(history)
    db.commit()
    db.refresh(order)

    # Real-Time Event Broadcast
    publish_order_event(
        order_id=order.id,
        event_type=EventType.ORDER_CANCELLED,
        data={
            "order_id": order.id,
            "old_status": old_status.value,
            "new_status": OrderStatus.CANCELLED.value,
            "reason": notes
        }
    )

    return order
