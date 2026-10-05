from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CartItemAdd(BaseModel):
    item_id: int = Field(..., description="ID of the menu item to add")
    quantity: int = Field(default=1, ge=1, le=50, description="Quantity to add")
    clear_existing: bool = Field(
        default=False,
        description="If True, clear existing cart items from another restaurant"
    )


class CartItemUpdate(BaseModel):
    quantity: int = Field(
        ...,
        ge=0,
        le=50,
        description="Set new item quantity. Setting to 0 removes the item."
    )


class CartItemResponse(BaseModel):
    id: int
    item_id: int
    name: str
    price: int  # in paise
    quantity: int
    subtotal: int  # in paise (price * quantity)
    is_veg: bool
    is_available: bool

    model_config = ConfigDict(from_attributes=True)


class CartResponse(BaseModel):
    id: int
    user_id: int
    restaurant_id: Optional[int] = None
    restaurant_name: Optional[str] = None
    items: List[CartItemResponse] = []
    total_item_count: int = 0
    subtotal: int = 0  # sum of item subtotals in paise
    delivery_fee: int = 0  # delivery fee in paise (₹40.00 = 4000)
    grand_total: int = 0  # subtotal + delivery_fee in paise

    model_config = ConfigDict(from_attributes=True)
