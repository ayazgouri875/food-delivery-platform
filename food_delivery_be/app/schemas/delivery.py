from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models.delivery import DeliveryStatus


class DeliveryPartnerProfile(BaseModel):
    vehicle_type: str = Field(default="BIKE", example="BIKE")
    vehicle_number: Optional[str] = Field(None, example="KA-01-AB-1234")
    current_city: str = Field(..., min_length=2, max_length=100, example="Bengaluru")


class DeliveryPartnerToggleOnline(BaseModel):
    is_online: bool = Field(..., description="Set online to accept delivery dispatch orders")


class DeliveryPartnerResponse(BaseModel):
    id: int
    user_id: int
    vehicle_type: str
    vehicle_number: Optional[str] = None
    current_city: str
    is_online: bool
    is_busy: bool
    rating: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeliveryStatusUpdate(BaseModel):
    status: DeliveryStatus


class DeliveryResponse(BaseModel):
    id: int
    order_id: int
    partner_id: Optional[int] = None
    status: DeliveryStatus
    assigned_at: datetime
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    restaurant_name: Optional[str] = None
    restaurant_address: Optional[str] = None
    delivery_address: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DeliveryLocationUpdate(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0, example=12.9716)
    longitude: float = Field(..., ge=-180.0, le=180.0, example=77.5946)
    heading: Optional[float] = Field(None, ge=0.0, le=360.0, description="Compass heading in degrees")
    speed: Optional[float] = Field(None, ge=0.0, description="Speed in km/h or m/s")


class DeliveryLocationResponse(BaseModel):
    partner_id: int
    latitude: float
    longitude: float
    heading: Optional[float] = None
    speed: Optional[float] = None
    distance_meters: Optional[float] = None
    eta_minutes: Optional[int] = None
    updated_at: float

