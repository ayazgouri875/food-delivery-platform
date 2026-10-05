from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class Address(Base):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(50), default="Home", nullable=False)  # e.g., "Home", "Office", "Other"
    address_line = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False, index=True)
    postal_code = Column(String(20), nullable=True)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ORM relationships
    user = relationship("User", backref="addresses")

    def __repr__(self):
        return f"<Address id={self.id} user_id={self.user_id} title='{self.title}'>"
