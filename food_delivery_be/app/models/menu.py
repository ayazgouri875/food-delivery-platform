from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    display_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ORM relationships
    restaurant = relationship("Restaurant", back_populates="categories")
    items = relationship("MenuItem", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<MenuCategory id={self.id} name='{self.name}' restaurant_id={self.restaurant_id}>"


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("menu_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    description = Column(String(500), nullable=True)
    
    # Store price in the smallest currency unit (paise/cents) to avoid floating-point math issues
    price = Column(Integer, nullable=False)
    
    is_available = Column(Boolean, default=True, nullable=False, index=True)
    is_veg = Column(Boolean, default=True, nullable=False)
    
    # Stock count: -1 = unlimited/made-to-order, >=0 = tracked inventory for concurrency testing
    stock_count = Column(Integer, default=-1, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ORM relationships
    restaurant = relationship("Restaurant", back_populates="menu_items")
    category = relationship("MenuCategory", back_populates="items")

    def __repr__(self):
        return f"<MenuItem id={self.id} name='{self.name}' price={self.price} available={self.is_available}>"
