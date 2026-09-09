from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    stock: int = 0
    image_url: Optional[str] = None
    category_id: int

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Product name cannot be empty")
        if len(value) < 2:
            raise ValueError("Product name must be at least 2 characters")
        if len(value) > 150:
            raise ValueError("Product name must be at most 150 characters")
        if value.isdigit():
            raise ValueError("Product name cannot be only numbers")
        return value

    @field_validator("price")
    @classmethod
    def validate_price(cls, value):
        if value <= 0:
            raise ValueError("Price must be greater than 0")
        if value > 10000000:
            raise ValueError("Price seems unrealistic, please check")
        return round(value, 2)

    @field_validator("stock")
    @classmethod
    def validate_stock(cls, value):
        if value < 0:
            raise ValueError("Stock cannot be negative")
        return value

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value):
        if value is None or value.strip() == "":
            return None
        value = value.strip()
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("Image URL must start with http:// or https://")
        if not any(
            value.lower().endswith(ext)
            for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]
        ):
            raise ValueError(
                "Image URL must point to a valid image file (.jpg, .png, .webp, etc.)"
            )
        return value


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = None
    image_url: Optional[str] = None
    category_id: Optional[int] = None

    @field_validator("price")
    @classmethod
    def validate_price(cls, value):
        if value is not None and value <= 0:
            raise ValueError("Price must be greater than 0")
        return round(value, 2) if value is not None else value

    @field_validator("stock")
    @classmethod
    def validate_stock(cls, value):
        if value is not None and value < 0:
            raise ValueError("Stock cannot be negative")
        return value

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value):
        if value is None or value.strip() == "":
            return None
        value = value.strip()
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("Image URL must start with http:// or https://")
        return value


class ProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    stock: int
    image_url: Optional[str] = None
    category_id: int
    vendor_id: int
    created_at: datetime

    class Config:
        from_attributes = True
