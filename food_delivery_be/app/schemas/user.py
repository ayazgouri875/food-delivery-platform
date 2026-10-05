from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, example="John Doe")
    email: EmailStr = Field(..., example="john.doe@example.com")
    phone: Optional[str] = Field(None, min_length=10, max_length=15, example="+919876543210")
    role: UserRole = Field(default=UserRole.CUSTOMER, example=UserRole.CUSTOMER)


class UserRegister(UserBase):
    password: str = Field(..., min_length=6, max_length=100, description="Plaintext password will be hashed")


class UserLogin(BaseModel):
    email: EmailStr = Field(..., example="john.doe@example.com")
    password: str = Field(..., min_length=1)


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenPayload(BaseModel):
    sub: Optional[str] = None  # user_id stored as string
    role: Optional[str] = None
    exp: Optional[int] = None
