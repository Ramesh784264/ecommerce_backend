"""
Coupons & Discounts Model

Table: coupons
  - Percentage or fixed-amount discount
  - Min order amount guard
  - Per-coupon usage limit + per-user usage limit
  - Active/inactive toggle
  - Expiry date

Table: coupon_usages
  - Tracks which user used which coupon (prevents re-use)
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.config.database import Base


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(Integer, primary_key=True, index=True)

    # The promo code customers enter at checkout (e.g., "SAVE20")
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)

    # Discount type: "percentage" | "fixed"
    discount_type = Column(String(20), nullable=False, default="percentage")

    # Discount value: e.g., 20 (means 20% or ₹20 depending on discount_type)
    discount_value = Column(Numeric(10, 2), nullable=False)

    # Minimum order amount required to apply this coupon
    min_order_amount = Column(Numeric(10, 2), default=0.00)

    # Maximum discount cap for percentage coupons (e.g., max ₹500 off on 30% coupon)
    max_discount_amount = Column(Numeric(10, 2), nullable=True)

    # Total number of times this coupon can be used (across all users). NULL = unlimited
    max_uses = Column(Integer, nullable=True)

    # Max times a single user can use this coupon
    max_uses_per_user = Column(Integer, default=1)

    # Actual usage count (incremented on each successful use)
    used_count = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    usages = relationship("CouponUsage", back_populates="coupon")


class CouponUsage(Base):
    __tablename__ = "coupon_usages"
    __table_args__ = (
        # Prevent same user from using same coupon more than allowed
        UniqueConstraint("coupon_id", "user_id", name="unique_coupon_user_usage"),
    )

    id = Column(Integer, primary_key=True, index=True)
    coupon_id = Column(Integer, ForeignKey("coupons.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)

    # Amount actually discounted for this usage
    discount_applied = Column(Numeric(10, 2), nullable=False)

    used_at = Column(DateTime(timezone=True), server_default=func.now())

    coupon = relationship("Coupon", back_populates="usages")
    user = relationship("User")
    order = relationship("Order")
