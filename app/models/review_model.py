"""
Reviews & Ratings Model

Table: reviews
  - One review per user per product (enforced via UniqueConstraint)
  - Rating: 1-5 integer
  - Optional title + body text
  - Admin can mark a review as verified/hidden
  - Vendor cannot review their own product
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.config.database import Base


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        # One review per user per product
        UniqueConstraint("user_id", "product_id", name="unique_user_product_review"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    rating = Column(Integer, nullable=False)         # 1–5
    title = Column(String(150), nullable=True)       # e.g., "Great quality!"
    body = Column(Text, nullable=True)               # Detailed review text

    # Moderation
    is_verified_purchase = Column(Boolean, default=False)  # Bought the product?
    is_visible = Column(Boolean, default=True)             # Admin can hide spam

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
    product = relationship("Product")
