from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("Category name cannot be empty")

        if len(value) < 2:
            raise ValueError("Category name must be at least 2 characters")

        if len(value) > 50:
            raise ValueError("Category name must be at most 50 characters")

        if value.isdigit():
            raise ValueError("Category name cannot be only numbers")

        if not any(char.isalpha() for char in value):
            raise ValueError("Category name must contain at least one letter")

        allowed_extra = {" ", "&", "-", "'"}
        if not all(char.isalnum() or char in allowed_extra for char in value):
            raise ValueError("Category name contains invalid characters")

        return value.title()

    @field_validator("description")
    @classmethod
    def validate_description(cls, value):
        if value is None:
            return value
        value = value.strip()
        if value and len(value) < 5:
            raise ValueError("Description must be at least 5 characters if provided")
        if len(value) > 255:
            raise ValueError("Description must be at most 255 characters")
        return value if value else None


class CategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
