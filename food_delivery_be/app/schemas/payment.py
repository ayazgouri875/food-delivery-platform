from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.models.payment import PaymentStatus


class PaymentInitiate(BaseModel):
    order_id: int = Field(..., description="Order ID to pay for")
    payment_method: str = Field(default="UPI", example="UPI")
    idempotency_key: str = Field(..., min_length=10, max_length=100, example="idem-uuid-98765-abcd")
    should_succeed: bool = Field(default=True, description="Mock toggle: set to false to test payment failure handling")
    simulate_gateway_outage: bool = Field(default=False, description="Mock toggle: simulate 502 gateway outage to test Circuit Breaker")


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    amount: int  # in paise
    status: PaymentStatus
    payment_method: str
    transaction_id: str
    idempotency_key: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
