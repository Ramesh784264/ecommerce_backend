"""
AI Feature Schemas

Request and response models for:
  - Product Recommendations
  - Smart Product Search
  - Rule-Based Chatbot
"""

from typing import Optional
from pydantic import BaseModel, Field


# ── Product Recommendations ──────────────────────────────────────────────────
class RecommendationItem(BaseModel):
    product_id: int
    name: str
    price: float
    stock: int
    image_url: Optional[str] = None
    avg_rating: float
    reason: str


class RecommendationResponse(BaseModel):
    user_id: Optional[int] = None
    count: int
    recommendations: list[RecommendationItem]


# ── Smart Search ─────────────────────────────────────────────────────────────
class SearchResultItem(BaseModel):
    product_id: int
    name: str
    description: Optional[str] = None
    price: float
    stock: int
    category: str
    image_url: Optional[str] = None
    avg_rating: float
    relevance_score: float


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResultItem]


# ── Chatbot ──────────────────────────────────────────────────────────────────
class ChatbotRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, description="Customer message or inquiry")


class ChatbotResponse(BaseModel):
    user_message: str
    reply: str
