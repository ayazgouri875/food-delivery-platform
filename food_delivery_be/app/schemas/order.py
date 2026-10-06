from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models.order import OrderStatus


class OrderCreate(BaseModel):
    delivery_address_id: int = Field(..., description="Saved delivery address ID")
    notes: Optional[str] = Field(None, max_length=255, description="Delivery or cooking instructions")
    idempotency_key: Optional[str] = Field(
        None,
        max_length=128,
        description="Client-generated unique key to prevent duplicate orders on retry or double-click"
    )


class OrderItemResponse(BaseModel):
    id: int
    item_id: Optional[int] = None
    item_name: str
    unit_price: int  # in paise
    quantity: int
    subtotal: int    # in paise

    model_config = ConfigDict(from_attributes=True)


class OrderStatusHistoryResponse(BaseModel):
    id: int
    old_status: Optional[str] = None
    new_status: str
    changed_by_user_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    notes: Optional[str] = Field(None, max_length=255)


class OrderResponse(BaseModel):
    id: int
    user_id: int
    restaurant_id: int
    delivery_address_id: Optional[int] = None
    delivery_address_snapshot: str
    status: OrderStatus
    subtotal: int
    delivery_fee: int
    grand_total: int
    idempotency_key: Optional[str] = None
    items: List[OrderItemResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OrderDetailResponse(OrderResponse):
    status_history: List[OrderStatusHistoryResponse] = []
