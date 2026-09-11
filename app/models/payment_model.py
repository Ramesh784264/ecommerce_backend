from sqlalchemy import Column, Integer, String, Numeric, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.config.database import Base


class PaymentLog(Base):
    """
    Audit trail for every payment event — Razorpay order creation,
    payment verification, webhook events, and refunds.
    """

    __tablename__ = "payment_logs"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)

    # Razorpay identifiers
    razorpay_order_id = Column(String(100), nullable=True, index=True)
    razorpay_payment_id = Column(String(100), nullable=True, index=True)
    razorpay_refund_id = Column(String(100), nullable=True)

    # Event type: created / captured / failed / refunded / webhook
    event_type = Column(String(50), nullable=False, index=True)

    # Amount in rupees (not paise) for readability
    amount = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(10), default="INR")

    # Raw response from Razorpay (for debugging)
    raw_response = Column(Text, nullable=True)

    # Error message if payment failed
    error_message = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order")
