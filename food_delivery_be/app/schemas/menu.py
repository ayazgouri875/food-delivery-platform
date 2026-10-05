from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.restaurant import RestaurantResponse


# Category Schemas
class MenuCategoryBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, example="Main Course")
    display_order: int = Field(default=0, ge=0, example=1)


class MenuCategoryCreate(MenuCategoryBase):
    pass


class MenuCategoryResponse(MenuCategoryBase):
    id: int
    restaurant_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Item Schemas
class MenuItemBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150, example="Hyderabadi Chicken Biryani")
    description: Optional[str] = Field(None, max_length=500, example="Fragrant basmati rice layered with spiced chicken")
    price: int = Field(..., gt=0, description="Price in paise (₹350.00 = 35000)", example=35000)
    is_available: bool = Field(default=True, example=True)
    is_veg: bool = Field(default=False, example=False)
    stock_count: int = Field(default=-1, description="-1 = unlimited, >=0 = exact stock", example=-1)


class MenuItemCreate(MenuItemBase):
    category_id: Optional[int] = Field(None, description="Category ID this item belongs to", example=1)


class MenuItemUpdate(BaseModel):
    category_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = Field(None, max_length=500)
    price: Optional[int] = Field(None, gt=0)
    is_veg: Optional[bool] = None
    stock_count: Optional[int] = None


class MenuItemAvailabilityUpdate(BaseModel):
    is_available: bool = Field(..., description="Toggle item availability in menu")


class MenuItemResponse(MenuItemBase):
    id: int
    restaurant_id: int
    category_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Aggregated Restaurant Menu Schema
class MenuCategoryWithItems(MenuCategoryResponse):
    items: List[MenuItemResponse] = []


class RestaurantFullMenuResponse(BaseModel):
    restaurant: RestaurantResponse
    categories: List[MenuCategoryWithItems]
    uncategorized_items: List[MenuItemResponse] = []
