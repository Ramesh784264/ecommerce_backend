from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


# ── CREATE (Admin only) ───────────────────────────────────────────────────────

class CouponCreate(BaseModel):
    code: str
    description: Optional[str] = None
    discount_type: str = "percentage"   # "percentage" | "fixed"
    discount_value: float
    min_order_amount: float = 0.0
    max_discount_amount: Optional[float] = None
    max_uses: Optional[int] = None
    max_uses_per_user: int = 1
    is_active: bool = True
    expires_at: Optional[datetime] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) < 3:
            raise ValueError("Coupon code must be at least 3 characters")
        if len(value) > 30:
            raise ValueError("Coupon code must be at most 30 characters")
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Coupon code can only contain letters, numbers, _ and -")
        return value

    @field_validator("discount_type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in ["percentage", "fixed"]:
            raise ValueError("discount_type must be 'percentage' or 'fixed'")
        return value

    @field_validator("discount_value")
    @classmethod
    def validate_value(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Discount value must be greater than 0")
        return value

    @field_validator("max_uses_per_user")
    @classmethod
    def validate_max_uses_per_user(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Max uses per user must be at least 1")
        return value


# ── UPDATE (Admin only) ──────────────────────────────────────────────────────

class CouponUpdate(BaseModel):
    description: Optional[str] = None
    discount_value: Optional[float] = None
    min_order_amount: Optional[float] = None
    max_discount_amount: Optional[float] = None
    max_uses: Optional[int] = None
    max_uses_per_user: Optional[int] = None
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None


# ── APPLY REQUEST (Customer) ──────────────────────────────────────────────────

class CouponApplyRequest(BaseModel):
    """Customer sends coupon code at checkout to get discount preview."""
    code: str
    order_amount: float  # Current cart total in INR

    @field_validator("order_amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Order amount must be greater than 0")
        return value


# ── RESPONSES ─────────────────────────────────────────────────────────────────

class CouponResponse(BaseModel):
    id: int
    code: str
    description: Optional[str]
    discount_type: str
    discount_value: float
    min_order_amount: float
    max_discount_amount: Optional[float]
    max_uses: Optional[int]
    max_uses_per_user: int
    used_count: int
    is_active: bool
    expires_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class CouponApplyResponse(BaseModel):
    """Result of applying a coupon code to a cart total."""
    valid: bool
    coupon_code: str
    discount_type: str
    discount_value: float
    discount_applied: float       # Actual amount deducted in INR
    original_amount: float        # Cart total before discount
    final_amount: float           # Cart total after discount
    message: str
