from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


# ──────────────────────────────────────────────
# REQUEST SCHEMAS
# ──────────────────────────────────────────────

class RazorpayOrderCreate(BaseModel):
    """
    Client sends this after placing a COD order to initiate Razorpay payment.
    The order must already exist in DB (created via /orders/checkout).
    """
    order_id: int


class PaymentVerifyRequest(BaseModel):
    """
    After Razorpay payment, frontend sends these 3 values for signature verification.
    All 3 are returned by Razorpay's checkout.js on successful payment.
    """
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

    @field_validator("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")
    @classmethod
    def must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty")
        return value


class RefundRequest(BaseModel):
    """
    Admin triggers a refund for a paid order.
    If amount is None, full refund is issued.
    """
    order_id: int
    amount: Optional[float] = None  # Partial refund amount in INR; None = full refund

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value):
        if value is not None and value <= 0:
            raise ValueError("Refund amount must be greater than 0")
        return value


# ──────────────────────────────────────────────
# RESPONSE SCHEMAS
# ──────────────────────────────────────────────

class RazorpayOrderResponse(BaseModel):
    """
    Sent to frontend after creating a Razorpay order.
    Frontend uses key_id + razorpay_order_id to open the checkout popup.
    """
    razorpay_order_id: str
    amount: int          # Amount in paise (₹1 = 100 paise)
    currency: str
    key_id: str          # Razorpay Key ID for frontend checkout popup
    order_db_id: int     # Our internal DB order ID


class PaymentVerifyResponse(BaseModel):
    """Response after successful payment verification."""
    success: bool
    message: str
    order_id: int
    payment_status: str


class PaymentStatusResponse(BaseModel):
    """Payment status for a given order."""
    order_id: int
    payment_status: str
    payment_method: Optional[str]
    razorpay_order_id: Optional[str]
    razorpay_payment_id: Optional[str]
    total_amount: float


class RefundResponse(BaseModel):
    """Response after triggering a refund."""
    success: bool
    message: str
    refund_id: Optional[str] = None
    refund_amount: Optional[float] = None


class PaymentLogResponse(BaseModel):
    """A single payment audit log entry."""
    id: int
    order_id: int
    razorpay_order_id: Optional[str]
    razorpay_payment_id: Optional[str]
    razorpay_refund_id: Optional[str]
    event_type: str
    amount: Optional[float]
    currency: str
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
