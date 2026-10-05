import enum
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    amount = Column(Integer, nullable=False)  # in paise
    status = Column(
        Enum(PaymentStatus, name="payment_status_enum", native_enum=False),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True
    )
    payment_method = Column(String(50), default="UPI", nullable=False)
    transaction_id = Column(String(100), unique=True, nullable=False, index=True)
    
    # Crucial for preventing duplicate transactions when retrying payments
    idempotency_key = Column(String(100), unique=True, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ORM relationships
    order = relationship("Order", back_populates="payment")

    def __repr__(self):
        return f"<Payment id={self.id} order_id={self.order_id} status={self.status} amount={self.amount}>"
