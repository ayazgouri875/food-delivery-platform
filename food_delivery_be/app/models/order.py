import enum
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class OrderStatus(str, enum.Enum):
    CREATED = "CREATED"                    # Placed from cart, awaiting payment
    CONFIRMED = "CONFIRMED"                # Payment verified, sent to restaurant
    PREPARING = "PREPARING"                # Kitchen accepted and cooking
    READY_FOR_PICKUP = "READY_FOR_PICKUP"  # Food ready, awaiting delivery partner
    PICKED_UP = "PICKED_UP"                # Delivery partner collected order
    DELIVERED = "DELIVERED"                # Successfully delivered to customer
    CANCELLED = "CANCELLED"                # Order cancelled


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Store the address ID as well as a text snapshot so user address edits never alter past orders
    delivery_address_id = Column(Integer, ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True)
    delivery_address_snapshot = Column(String(500), nullable=False)
    
    status = Column(
        Enum(OrderStatus, name="order_status_enum", native_enum=False),
        default=OrderStatus.CREATED,
        nullable=False,
        index=True
    )
    
    # Financial snapshots stored in paise (integers)
    subtotal = Column(Integer, nullable=False)
    delivery_fee = Column(Integer, default=4000, nullable=False)
    grand_total = Column(Integer, nullable=False)
    # Idempotency key for preventing duplicate orders on network retries
    idempotency_key = Column(String(100), unique=True, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ORM relationships
    user = relationship("User", backref="orders")
    restaurant = relationship("Restaurant", backref="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    status_history = relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan")
    payment = relationship("Payment", back_populates="order", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Order id={self.id} user_id={self.user_id} status={self.status} total={self.grand_total}>"


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True)
    
    # Price and name snapshot at checkout time (prevents menu updates from changing past invoices)
    item_name = Column(String(150), nullable=False)
    unit_price = Column(Integer, nullable=False)  # in paise
    quantity = Column(Integer, nullable=False)
    subtotal = Column(Integer, nullable=False)    # unit_price * quantity in paise

    # ORM relationships
    order = relationship("Order", back_populates="items")
    item = relationship("MenuItem")

    def __repr__(self):
        return f"<OrderItem id={self.id} order_id={self.order_id} name='{self.item_name}' qty={self.quantity}>"


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ORM relationships
    order = relationship("Order", back_populates="status_history")
    changed_by = relationship("User")

    def __repr__(self):
        return f"<OrderStatusHistory order_id={self.order_id} {self.old_status} -> {self.new_status}>"
