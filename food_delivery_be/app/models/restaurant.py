from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    address_line = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False, index=True)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)
    
    # Platform admin approval status (KYC / food license verification)
    is_active = Column(Boolean, default=False, nullable=False, index=True)
    
    # Store daily operation status toggled by the restaurant owner
    is_open = Column(Boolean, default=True, nullable=False, index=True)
    
    rating = Column(Float, default=0.0, nullable=False)
    total_ratings = Column(Integer, default=0, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ORM relationships
    owner = relationship("User", backref="restaurants")
    categories = relationship("MenuCategory", back_populates="restaurant", cascade="all, delete-orphan")
    menu_items = relationship("MenuItem", back_populates="restaurant", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Restaurant id={self.id} name='{self.name}' city='{self.city}' active={self.is_active}>"
