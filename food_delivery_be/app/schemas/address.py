from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class AddressBase(BaseModel):
    title: str = Field(default="Home", min_length=1, max_length=50, example="Home")
    address_line: str = Field(..., min_length=5, max_length=255, example="Flat 402, Sunshine Apartments, Koramangala")
    city: str = Field(..., min_length=2, max_length=100, example="Bengaluru")
    postal_code: Optional[str] = Field(None, max_length=20, example="560034")
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, example=12.9352)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, example=77.6245)
    is_default: bool = Field(default=False, example=True)


class AddressCreate(AddressBase):
    pass


class AddressResponse(AddressBase):
    id: int
    user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
