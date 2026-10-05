from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db
from app.models.cart import Cart, CartItem
from app.models.menu import MenuItem
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.cart import (
    CartItemAdd,
    CartItemResponse,
    CartItemUpdate,
    CartResponse,
)

router = APIRouter(prefix="/cart", tags=["Cart"])

DELIVERY_FEE_PAISE = 4000  # Flat ₹40.00 mock delivery fee


def _get_or_create_cart(user_id: int, db: Session) -> Cart:
    """Retrieve the user's cart, or create an empty one if not exists."""
    cart = db.query(Cart).filter(Cart.user_id == user_id).first()
    if not cart:
        cart = Cart(user_id=user_id, restaurant_id=None)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart


def _build_cart_response(cart: Cart, db: Session) -> CartResponse:
    """
    Compute item subtotals, delivery fee, and grand total in paise.
    Also handles cleanup if all items were removed.
    """
    items_response: list[CartItemResponse] = []
    subtotal = 0
    total_count = 0

    restaurant_name = None
    if cart.restaurant_id:
        restaurant = db.query(Restaurant).filter(Restaurant.id == cart.restaurant_id).first()
        if restaurant:
            restaurant_name = restaurant.name

    for cart_item in cart.items:
        menu_item = cart_item.item
        if menu_item:
            item_subtotal = menu_item.price * cart_item.quantity
            subtotal += item_subtotal
            total_count += cart_item.quantity

            items_response.append(
                CartItemResponse(
                    id=cart_item.id,
                    item_id=menu_item.id,
                    name=menu_item.name,
                    price=menu_item.price,
                    quantity=cart_item.quantity,
                    subtotal=item_subtotal,
                    is_veg=menu_item.is_veg,
                    is_available=menu_item.is_available
                )
            )

    delivery_fee = DELIVERY_FEE_PAISE if total_count > 0 else 0
    grand_total = subtotal + delivery_fee

    return CartResponse(
        id=cart.id,
        user_id=cart.user_id,
        restaurant_id=cart.restaurant_id,
        restaurant_name=restaurant_name,
        items=items_response,
        total_item_count=total_count,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        grand_total=grand_total
    )


@router.get(
    "/",
    response_model=CartResponse,
    summary="Get current customer's cart"
)
def get_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cart = _get_or_create_cart(current_user.id, db)
    return _build_cart_response(cart, db)


@router.post(
    "/items",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Add an item to the cart (enforces single-restaurant rule)"
)
def add_item_to_cart(
    item_in: CartItemAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cart = _get_or_create_cart(current_user.id, db)

    # 1. Fetch and validate menu item
    menu_item = db.query(MenuItem).filter(MenuItem.id == item_in.item_id).first()
    if not menu_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu item not found"
        )

    if not menu_item.is_available:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{menu_item.name}' is currently out of stock."
        )

    # 2. Validate restaurant status
    restaurant = db.query(Restaurant).filter(Restaurant.id == menu_item.restaurant_id).first()
    if not restaurant or not restaurant.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Restaurant is currently inactive."
        )
    if not restaurant.is_open:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{restaurant.name}' is currently closed and not accepting orders."
        )

    # 3. Enforce Single-Restaurant Rule
    if cart.restaurant_id is not None and cart.restaurant_id != menu_item.restaurant_id:
        if not item_in.clear_existing:
            existing_restaurant = db.query(Restaurant).filter(Restaurant.id == cart.restaurant_id).first()
            existing_name = existing_restaurant.name if existing_restaurant else "another restaurant"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Your cart already contains items from '{existing_name}'. "
                    f"A food order can only contain items from a single restaurant. "
                    f"Set clear_existing=true to discard the previous cart and add this item."
                )
            )
        else:
            # Clear existing items and reset restaurant
            db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
            cart.restaurant_id = menu_item.restaurant_id
            db.flush()

    # Assign restaurant to cart if previously empty
    if cart.restaurant_id is None:
        cart.restaurant_id = menu_item.restaurant_id

    # 4. Check if item already exists in cart; increment quantity if so
    cart_item = db.query(CartItem).filter(
        CartItem.cart_id == cart.id,
        CartItem.item_id == menu_item.id
    ).first()

    if cart_item:
        cart_item.quantity += item_in.quantity
    else:
        new_cart_item = CartItem(
            cart_id=cart.id,
            item_id=menu_item.id,
            quantity=item_in.quantity
        )
        db.add(new_cart_item)

    db.commit()
    db.refresh(cart)
    return _build_cart_response(cart, db)


@router.patch(
    "/items/{item_id}",
    response_model=CartResponse,
    summary="Update cart item quantity (0 removes item)"
)
def update_cart_item_quantity(
    item_id: int,
    update_in: CartItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cart = _get_or_create_cart(current_user.id, db)

    cart_item = db.query(CartItem).filter(
        CartItem.cart_id == cart.id,
        CartItem.item_id == item_id
    ).first()

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found in your cart."
        )

    if update_in.quantity == 0:
        db.delete(cart_item)
    else:
        cart_item.quantity = update_in.quantity

    db.flush()

    # If cart is now empty, reset restaurant_id to None
    remaining_count = db.query(CartItem).filter(CartItem.cart_id == cart.id).count()
    if remaining_count == 0:
        cart.restaurant_id = None

    db.commit()
    db.refresh(cart)
    return _build_cart_response(cart, db)


@router.delete(
    "/items/{item_id}",
    response_model=CartResponse,
    summary="Remove a specific item from cart"
)
def remove_cart_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cart = _get_or_create_cart(current_user.id, db)

    cart_item = db.query(CartItem).filter(
        CartItem.cart_id == cart.id,
        CartItem.item_id == item_id
    ).first()

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found in your cart."
        )

    db.delete(cart_item)
    db.flush()

    remaining_count = db.query(CartItem).filter(CartItem.cart_id == cart.id).count()
    if remaining_count == 0:
        cart.restaurant_id = None

    db.commit()
    db.refresh(cart)
    return _build_cart_response(cart, db)


@router.delete(
    "/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear all items from cart"
)
def clear_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cart = _get_or_create_cart(current_user.id, db)
    db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
    cart.restaurant_id = None
    db.commit()
    return None
