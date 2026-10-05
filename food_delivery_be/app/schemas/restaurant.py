from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class RestaurantBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150, example="Paradise Biryani")
    address_line: str = Field(..., min_length=5, max_length=255, example="123 MG Road, Indiranagar")
    city: str = Field(..., min_length=2, max_length=100, example="Bengaluru")
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, example=12.9716)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, example=77.5946)


class RestaurantCreate(RestaurantBase):
    pass


class RestaurantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    address_line: Optional[str] = Field(None, min_length=5, max_length=255)
    city: Optional[str] = Field(None, min_length=2, max_length=100)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)


class RestaurantStatusUpdate(BaseModel):
    is_active: bool = Field(..., description="Admin activation/approval flag")


class RestaurantToggleOpen(BaseModel):
    is_open: bool = Field(..., description="Owner open/closed toggle")


class RestaurantResponse(RestaurantBase):
    id: int
    owner_id: int
    is_active: bool
    is_open: bool
    rating: float
    total_ratings: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
