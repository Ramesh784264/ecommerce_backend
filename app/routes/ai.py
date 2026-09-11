"""
AI Feature Routes

Endpoints:
  GET  /ai/recommendations         → Personalized recommendations for authenticated customer
  GET  /ai/recommendations/popular → Popular product recommendations for guest/anonymous users
  GET  /ai/search                  → Smart multi-signal fuzzy search with synonym expansion
  POST /ai/chatbot                 → Automated customer support chatbot endpoint
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user_model import User
from app.schemas.ai_schema import (
    ChatbotRequest,
    ChatbotResponse,
    RecommendationItem,
    RecommendationResponse,
    SearchResponse,
    SearchResultItem,
)
from app.utils.ai_utils import (
    chatbot_respond,
    get_recommendations,
    smart_search,
)
from app.utils.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Features"])


# ─────────────────────────────────────────────────────────────────────────────
# 1. PRODUCT RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/recommendations",
    response_model=RecommendationResponse,
    summary="Personalized product recommendations for logged-in user",
)
def get_user_recommendations(
    limit: int = Query(10, ge=1, le=50, description="Max number of recommendations"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns AI-powered product recommendations for the authenticated customer.

    Algorithm:
      1. Collaborative filtering: products bought by users with similar taste
      2. Category affinities: products in categories the user frequently buys
      3. Fallback: highest-rated and most-reviewed active products
    """
    items = get_recommendations(user_id=current_user.id, db=db, limit=limit)
    return RecommendationResponse(
        user_id=current_user.id,
        count=len(items),
        recommendations=items,
    )


@router.get(
    "/recommendations/popular",
    response_model=RecommendationResponse,
    summary="Popular product recommendations for guest or new users",
)
def get_popular_recommendations(
    limit: int = Query(10, ge=1, le=50, description="Max number of recommendations"),
    db: Session = Depends(get_db),
):
    """
    Returns top-rated popular products for guests or unauthenticated users.
    """
    # Passing user_id=0 triggers the popularity/rating fallback
    items = get_recommendations(user_id=0, db=db, limit=limit)
    return RecommendationResponse(
        user_id=None,
        count=len(items),
        recommendations=items,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. SMART PRODUCT SEARCH
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Smart product search with fuzzy matching, synonyms & relevance scoring",
)
def search_products(
    q: str = Query(..., min_length=1, max_length=100, description="Search term, keyword, or misspelling"),
    category_id: Optional[int] = Query(None, description="Filter by category ID"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum price filter"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum price filter"),
    min_rating: Optional[float] = Query(None, ge=1, le=5, description="Minimum rating filter (1-5)"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
    db: Session = Depends(get_db),
):
    """
    Multi-signal AI search engine:
      - Handles spelling errors & typos using Levenshtein/SequenceMatcher fuzzy matching
      - Automatically expands query with product domain synonyms (e.g. 'phone' -> 'mobile', 'smartphone')
      - Scores products based on exact name match, prefix match, substring match, description, and category
      - Filters by category, price range, and rating
      - Returns results ranked by relevance score desc
    """
    results = smart_search(
        query=q,
        db=db,
        category_id=category_id,
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        limit=limit,
    )
    return SearchResponse(
        query=q,
        total=len(results),
        results=results,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. CHATBOT FAQ ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/chatbot",
    response_model=ChatbotResponse,
    summary="Customer support virtual assistant",
)
def chatbot_chat(
    data: ChatbotRequest,
):
    """
    Automated customer assistance bot for instant answers on:
      - Order status and tracking
      - Cancellation, returns, and refunds
      - Payment issues and Razorpay status
      - Shipping speed, delivery charges, and Cash on Delivery (COD)
      - Coupons and promotional discounts
      - Account, login, and password resets
      - Escalation to human support
    """
    reply = chatbot_respond(data.message)
    return ChatbotResponse(
        user_message=data.message,
        reply=reply,
    )
