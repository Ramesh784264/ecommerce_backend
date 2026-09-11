from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


# ── CREATE ───────────────────────────────────────────────────────────────────

class ReviewCreate(BaseModel):
    product_id: int
    rating: int
    title: Optional[str] = None
    body: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("Rating must be between 1 and 5")
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, value):
        if value is None:
            return value
        value = value.strip()
        if len(value) > 150:
            raise ValueError("Title must be at most 150 characters")
        return value if value else None

    @field_validator("body")
    @classmethod
    def validate_body(cls, value):
        if value is None:
            return value
        value = value.strip()
        if value and len(value) < 10:
            raise ValueError("Review body must be at least 10 characters if provided")
        if len(value) > 2000:
            raise ValueError("Review body must be at most 2000 characters")
        return value if value else None


# ── UPDATE ───────────────────────────────────────────────────────────────────

class ReviewUpdate(BaseModel):
    rating: Optional[int] = None
    title: Optional[str] = None
    body: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value):
        if value is not None and (value < 1 or value > 5):
            raise ValueError("Rating must be between 1 and 5")
        return value


# ── RESPONSE ──────────────────────────────────────────────────────────────────

class ReviewerInfo(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class ReviewResponse(BaseModel):
    id: int
    product_id: int
    user_id: int
    rating: int
    title: Optional[str] = None
    body: Optional[str] = None
    is_verified_purchase: bool
    is_visible: bool
    created_at: datetime
    user: ReviewerInfo

    class Config:
        from_attributes = True


class ProductRatingSummary(BaseModel):
    """Aggregated rating stats for a product."""
    product_id: int
    total_reviews: int
    average_rating: float
    rating_breakdown: dict[str, int]  # {"5": 10, "4": 5, ...}
