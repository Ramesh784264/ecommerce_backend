from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
from app.schemas.product_schema import ProductResponse


# ---------------- CHECKOUT REQUEST ----------------
class CheckoutRequest(BaseModel):
    shipping_name: str
    shipping_phone: str
    shipping_address: str
    shipping_city: str
    shipping_pincode: str

    @field_validator("shipping_name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Name must be at least 2 characters")
        if len(value) > 100:
            raise ValueError("Name must be at most 100 characters")
        if value[0].isdigit():
            raise ValueError("Name cannot start with a number")
        if not any(char.isalpha() for char in value):
            raise ValueError("Name must contain at least one letter")
        return value

    @field_validator("shipping_phone")
    @classmethod
    def validate_phone(cls, value):
        value = value.strip()
        if not value.isdigit():
            raise ValueError("Phone number must contain only digits")
        if len(value) != 10:
            raise ValueError("Phone number must be exactly 10 digits")
        if value[0] not in ["6", "7", "8", "9"]:
            raise ValueError("Phone number must start with 6, 7, 8, or 9")
        return value

    @field_validator("shipping_pincode")
    @classmethod
    def validate_pincode(cls, value):
        value = value.strip()
        if not value.isdigit():
            raise ValueError("Pincode must contain only digits")
        if len(value) != 6:
            raise ValueError("Pincode must be exactly 6 digits")
        return value

    @field_validator("shipping_address")
    @classmethod
    def validate_address(cls, value):
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Address must be at least 10 characters")
        if len(value) > 255:
            raise ValueError("Address must be at most 255 characters")
        return value


# ---------------- ORDER ITEM RESPONSE ----------------
class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    price_at_purchase: float
    product: ProductResponse

    class Config:
        from_attributes = True


# ---------------- ORDER RESPONSE ----------------
class OrderResponse(BaseModel):
    id: int
    user_id: int
    total_amount: float
    status: str
    payment_status: str
    payment_method: Optional[str] = None
    shipping_name: str
    shipping_phone: str
    shipping_address: str
    shipping_city: str
    shipping_pincode: str
    created_at: datetime
    items: List[OrderItemResponse]

    class Config:
        from_attributes = True


# ---------------- STATUS UPDATE (Admin/Vendor) ----------------
class OrderStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        allowed = ["pending", "confirmed", "shipped", "delivered", "cancelled"]
        if value not in allowed:
            raise ValueError(f"Status must be one of: {', '.join(allowed)}")
        return value
