from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.config.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    total_amount = Column(Numeric(10, 2), nullable=False)
    discount_amount = Column(Numeric(10, 2), default=0.00)  # Coupon discount applied
    status = Column(
        String(20), default="pending", index=True
    )  # pending / confirmed / shipped / delivered / cancelled

    # Payment details (Razorpay integration ku)
    payment_status = Column(
        String(20), default="unpaid", index=True
    )  # unpaid / paid / failed / refund_pending / refunded
    payment_method = Column(String(20), nullable=True)  # razorpay / cod
    razorpay_order_id = Column(String(100), nullable=True, index=True)
    razorpay_payment_id = Column(String(100), nullable=True)
    razorpay_signature = Column(String(255), nullable=True)

    shipping_name = Column(String(100), nullable=False)
    shipping_phone = Column(String(15), nullable=False)
    shipping_address = Column(String(255), nullable=False)
    shipping_city = Column(String(100), nullable=False)
    shipping_pincode = Column(String(10), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
    items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    quantity = Column(Integer, nullable=False)
    price_at_purchase = Column(
        Numeric(10, 2), nullable=False
    )  # order panna neram price freeze pannuvom

    order = relationship("Order", back_populates="items")
    product = relationship("Product")
