from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.dependencies.auth import get_current_user, require_role
from app.dependencies.database import get_db
from app.models.delivery import Delivery, DeliveryPartner, DeliveryStatus
from app.models.order import Order, OrderStatus, OrderStatusHistory
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.delivery import (
    DeliveryPartnerProfile,
    DeliveryPartnerResponse,
    DeliveryPartnerToggleOnline,
    DeliveryResponse,
    DeliveryStatusUpdate,
)

router = APIRouter(prefix="/delivery", tags=["Delivery & Fulfillment"])


def _build_delivery_response(delivery: Delivery) -> DeliveryResponse:
    restaurant_name = None
    restaurant_address = None
    delivery_address = None

    if delivery.order:
        delivery_address = delivery.order.delivery_address_snapshot
        if delivery.order.restaurant:
            restaurant_name = delivery.order.restaurant.name
            restaurant_address = delivery.order.restaurant.address_line

    return DeliveryResponse(
        id=delivery.id,
        order_id=delivery.order_id,
        partner_id=delivery.partner_id,
        status=delivery.status,
        assigned_at=delivery.assigned_at,
        picked_up_at=delivery.picked_up_at,
        delivered_at=delivery.delivered_at,
        restaurant_name=restaurant_name,
        restaurant_address=restaurant_address,
        delivery_address=delivery_address
    )


# -------------------------------------------------------------
# Delivery Partner Profile & Online Toggle
# -------------------------------------------------------------

@router.post(
    "/partner/profile",
    response_model=DeliveryPartnerResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or update delivery partner profile"
)
def upsert_partner_profile(
    profile_in: DeliveryPartnerProfile,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.DELIVERY_PARTNER, UserRole.ADMIN]))
):
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == current_user.id).first()
    if not partner:
        partner = DeliveryPartner(
            user_id=current_user.id,
            vehicle_type=profile_in.vehicle_type,
            vehicle_number=profile_in.vehicle_number,
            current_city=profile_in.current_city,
            is_online=True,
            is_busy=False
        )
        db.add(partner)
    else:
        partner.vehicle_type = profile_in.vehicle_type
        partner.vehicle_number = profile_in.vehicle_number
        partner.current_city = profile_in.current_city

    db.commit()
    db.refresh(partner)
    return partner


@router.get(
    "/partner/me",
    response_model=DeliveryPartnerResponse,
    summary="Get current delivery partner profile"
)
def get_partner_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.DELIVERY_PARTNER, UserRole.ADMIN]))
):
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == current_user.id).first()
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery partner profile not found. Please create your profile first."
        )
    return partner


@router.patch(
    "/partner/status",
    response_model=DeliveryPartnerResponse,
    summary="Toggle delivery partner online / offline status"
)
def toggle_partner_online(
    status_in: DeliveryPartnerToggleOnline,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.DELIVERY_PARTNER, UserRole.ADMIN]))
):
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == current_user.id).first()
    if not partner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partner profile not found.")

    partner.is_online = status_in.is_online
    db.commit()
    db.refresh(partner)
    return partner


# -------------------------------------------------------------
# Dispatch Assignment & Order Fulfillment
# -------------------------------------------------------------

@router.post(
    "/assign/{order_id}",
    response_model=DeliveryResponse,
    summary="Dispatch order to an available online delivery partner"
)
def assign_delivery_partner(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Rider dispatch algorithm:
    1. Validates order status (must be READY_FOR_PICKUP or CONFIRMED).
    2. Checks if order already has an active delivery assigned.
    3. Finds an available delivery partner who is:
       - in the same city as the restaurant
       - is_online == True
       - is_busy == False
    4. Locks partner as busy and creates Delivery record.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order.status not in [OrderStatus.READY_FOR_PICKUP, OrderStatus.CONFIRMED, OrderStatus.PREPARING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign delivery for order in '{order.status}' status."
        )

    # Check for existing delivery
    existing_delivery = db.query(Delivery).filter(
        Delivery.order_id == order.id,
        Delivery.status != DeliveryStatus.CANCELLED
    ).first()
    if existing_delivery:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Delivery already assigned (Partner ID: {existing_delivery.partner_id})."
        )

    restaurant = db.query(Restaurant).filter(Restaurant.id == order.restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    # Find available partner in the restaurant's city
    partner = db.query(DeliveryPartner).filter(
        DeliveryPartner.current_city.ilike(restaurant.city),
        DeliveryPartner.is_online == True,
        DeliveryPartner.is_busy == False
    ).first()

    if not partner:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No delivery partners currently online in {restaurant.city}. Please retry shortly."
        )

    # Assign partner and mark as busy
    partner.is_busy = True

    delivery = Delivery(
        order_id=order.id,
        partner_id=partner.id,
        status=DeliveryStatus.ASSIGNED
    )
    db.add(delivery)

    # Record history on order
    history = OrderStatusHistory(
        order_id=order.id,
        old_status=order.status.value,
        new_status=order.status.value,
        changed_by_user_id=current_user.id,
        notes=f"Delivery partner assigned (Partner ID: {partner.id}, Rider: {partner.user.name})"
    )
    db.add(history)

    db.commit()
    db.refresh(delivery)
    return _build_delivery_response(delivery)


@router.get(
    "/my-deliveries",
    response_model=List[DeliveryResponse],
    summary="Get all deliveries assigned to the current partner"
)
def list_my_deliveries(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.DELIVERY_PARTNER]))
):
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == current_user.id).first()
    if not partner:
        return []

    deliveries = db.query(Delivery).filter(Delivery.partner_id == partner.id).order_by(Delivery.assigned_at.desc()).all()
    return [_build_delivery_response(d) for d in deliveries]


@router.patch(
    "/{delivery_id}/status",
    response_model=DeliveryResponse,
    summary="Update delivery status (PICKED_UP -> DELIVERED)"
)
def update_delivery_status(
    delivery_id: int,
    status_in: DeliveryStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role([UserRole.DELIVERY_PARTNER, UserRole.ADMIN]))
):
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery record not found")

    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == current_user.id).first()
    if current_user.role != UserRole.ADMIN and (not partner or delivery.partner_id != partner.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this delivery")

    now = datetime.now(timezone.utc)
    order = delivery.order

    if status_in.status == DeliveryStatus.PICKED_UP:
        delivery.status = DeliveryStatus.PICKED_UP
        delivery.picked_up_at = now
        
        # Synchronize order status
        if order:
            old_order_status = order.status
            order.status = OrderStatus.PICKED_UP
            history = OrderStatusHistory(
                order_id=order.id,
                old_status=old_order_status.value,
                new_status=OrderStatus.PICKED_UP.value,
                changed_by_user_id=current_user.id,
                notes="Delivery partner picked up food from restaurant"
            )
            db.add(history)

    elif status_in.status == DeliveryStatus.DELIVERED:
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = now
        
        # Free the delivery partner to accept future dispatches!
        if delivery.partner:
            delivery.partner.is_busy = False

        # Synchronize order status to DELIVERED
        if order:
            old_order_status = order.status
            order.status = OrderStatus.DELIVERED
            history = OrderStatusHistory(
                order_id=order.id,
                old_status=old_order_status.value,
                new_status=OrderStatus.DELIVERED.value,
                changed_by_user_id=current_user.id,
                notes="Order successfully delivered to customer"
            )
            db.add(history)

    db.commit()
    db.refresh(delivery)
    return _build_delivery_response(delivery)
