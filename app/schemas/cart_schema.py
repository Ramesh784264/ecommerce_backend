from pydantic import BaseModel
from datetime import datetime
from app.schemas.product_schema import ProductResponse


class CartItemCreate(BaseModel):
    product_id: int
    quantity: int = 1


class CartItemUpdate(BaseModel):
    quantity: int


class CartItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    product: ProductResponse
    created_at: datetime

    class Config:
        from_attributes = True
