import enum
from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class DeliveryStatus(str, enum.Enum):
    ASSIGNED = "ASSIGNED"        # Dispatched to driver
    PICKED_UP = "PICKED_UP"      # Collected from kitchen
    DELIVERED = "DELIVERED"      # Reached customer
    CANCELLED = "CANCELLED"


class DeliveryPartner(Base):
    __tablename__ = "delivery_partners"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    vehicle_type = Column(String(50), default="BIKE", nullable=False)
    vehicle_number = Column(String(50), nullable=True)
    current_city = Column(String(100), nullable=False, index=True)
    
    # Online status controls whether the partner is available to receive assignments
    is_online = Column(Boolean, default=False, nullable=False, index=True)
    
    # Busy status indicates the partner is actively fulfilling another delivery
    is_busy = Column(Boolean, default=False, nullable=False, index=True)
    
    rating = Column(Float, default=5.0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ORM relationships
    user = relationship("User", backref="delivery_profile", uselist=False)
    deliveries = relationship("Delivery", back_populates="partner")

    def __repr__(self):
        return f"<DeliveryPartner id={self.id} user_id={self.user_id} online={self.is_online} busy={self.is_busy}>"


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    partner_id = Column(Integer, ForeignKey("delivery_partners.id", ondelete="SET NULL"), nullable=True, index=True)
    
    status = Column(
        Enum(DeliveryStatus, name="delivery_status_enum", native_enum=False),
        default=DeliveryStatus.ASSIGNED,
        nullable=False,
        index=True
    )
    
    assigned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    picked_up_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    # ORM relationships
    order = relationship("Order", backref="delivery", uselist=False)
    partner = relationship("DeliveryPartner", back_populates="deliveries")

    def __repr__(self):
        return f"<Delivery id={self.id} order_id={self.order_id} partner_id={self.partner_id} status={self.status}>"
