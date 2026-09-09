from pydantic import BaseModel
from datetime import datetime
from app.schemas.product_schema import ProductResponse


class WishlistItemCreate(BaseModel):
    product_id: int


class WishlistItemResponse(BaseModel):
    id: int
    product_id: int
    product: ProductResponse
    created_at: datetime

    class Config:
        from_attributes = True
