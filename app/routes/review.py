"""
Reviews & Ratings Routes

Endpoints:
  POST   /reviews/                          → Submit a review (verified purchase check)
  GET    /reviews/product/{product_id}      → Get all reviews for a product
  GET    /reviews/product/{product_id}/summary → Rating summary (avg, breakdown)
  GET    /reviews/my-reviews               → Customer's own reviews
  PUT    /reviews/{review_id}              → Edit own review
  DELETE /reviews/{review_id}             → Delete own review (or admin)
  PUT    /reviews/{review_id}/toggle-visibility → Admin: hide/show a review

Business Rules:
  - A user must have purchased the product to leave a review (is_verified_purchase)
  - A vendor cannot review their own product
  - Only visible reviews are shown to the public
  - Admin can hide reviews (spam, abuse)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.order_model import Order, OrderItem
from app.models.product_model import Product
from app.models.review_model import Review
from app.models.user_model import User
from app.schemas.review_schema import (
    ProductRatingSummary,
    ReviewCreate,
    ReviewResponse,
    ReviewUpdate,
)
from app.utils.dependencies import get_current_user, role_required

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviews", tags=["Reviews & Ratings"])


def _check_verified_purchase(user_id: int, product_id: int, db: Session) -> bool:
    """
    Check if the user has purchased this product (any delivered order).
    Used to mark reviews as 'verified purchase'.
    """
    delivered_order = (
        db.query(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(
            Order.user_id == user_id,
            OrderItem.product_id == product_id,
            Order.status == "delivered",
        )
        .first()
    )
    return delivered_order is not None


# ──────────────────────────────────────────────
# SUBMIT REVIEW
# ──────────────────────────────────────────────

@router.post("/", response_model=ReviewResponse)
def create_review(
    data: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Submit a review for a product.
    - Customer must be logged in
    - Cannot review same product twice
    - Vendor cannot review their own product
    """
    product = db.query(Product).filter(
        Product.id == data.product_id, Product.is_active == True
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Vendor cannot review their own product
    if current_user.role == "vendor" and product.vendor_id == current_user.id:
        raise HTTPException(
            status_code=403, detail="You cannot review your own product"
        )

    # Check duplicate review
    existing = (
        db.query(Review)
        .filter(
            Review.user_id == current_user.id,
            Review.product_id == data.product_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="You have already reviewed this product. You can edit your existing review.",
        )

    # Check verified purchase
    is_verified = _check_verified_purchase(current_user.id, data.product_id, db)

    review = Review(
        user_id=current_user.id,
        product_id=data.product_id,
        rating=data.rating,
        title=data.title,
        body=data.body,
        is_verified_purchase=is_verified,
        is_visible=True,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    logger.info(
        f"Review created: user_id={current_user.id}, product_id={data.product_id}, "
        f"rating={data.rating}, verified={is_verified}"
    )
    return review


# ──────────────────────────────────────────────
# GET REVIEWS FOR A PRODUCT
# ──────────────────────────────────────────────

@router.get("/product/{product_id}", response_model=list[ReviewResponse])
def get_product_reviews(
    product_id: int,
    rating: Optional[int] = Query(None, ge=1, le=5, description="Filter by star rating"),
    verified_only: bool = Query(False, description="Show only verified purchase reviews"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Get all visible reviews for a product.
    Optionally filter by rating (1-5) or verified purchases only.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    query = db.query(Review).filter(
        Review.product_id == product_id,
        Review.is_visible == True,
    )

    if rating is not None:
        query = query.filter(Review.rating == rating)
    if verified_only:
        query = query.filter(Review.is_verified_purchase == True)

    return (
        query.order_by(Review.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# ──────────────────────────────────────────────
# RATING SUMMARY FOR A PRODUCT
# ──────────────────────────────────────────────

@router.get("/product/{product_id}/summary", response_model=ProductRatingSummary)
def get_product_rating_summary(product_id: int, db: Session = Depends(get_db)):
    """
    Returns average rating and star-breakdown for a product.
    Example: {"5": 42, "4": 18, "3": 5, "2": 2, "1": 1}
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    reviews = (
        db.query(Review)
        .filter(Review.product_id == product_id, Review.is_visible == True)
        .all()
    )

    total = len(reviews)
    if total == 0:
        return ProductRatingSummary(
            product_id=product_id,
            total_reviews=0,
            average_rating=0.0,
            rating_breakdown={"5": 0, "4": 0, "3": 0, "2": 0, "1": 0},
        )

    breakdown = {str(i): 0 for i in range(1, 6)}
    total_rating = 0
    for r in reviews:
        breakdown[str(r.rating)] += 1
        total_rating += r.rating

    avg = round(total_rating / total, 1)

    return ProductRatingSummary(
        product_id=product_id,
        total_reviews=total,
        average_rating=avg,
        rating_breakdown=breakdown,
    )


# ──────────────────────────────────────────────
# MY REVIEWS
# ──────────────────────────────────────────────

@router.get("/my-reviews", response_model=list[ReviewResponse])
def get_my_reviews(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all reviews submitted by the current logged-in user."""
    return (
        db.query(Review)
        .filter(Review.user_id == current_user.id)
        .order_by(Review.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# ──────────────────────────────────────────────
# EDIT OWN REVIEW
# ──────────────────────────────────────────────

@router.put("/{review_id}", response_model=ReviewResponse)
def update_review(
    review_id: int,
    data: ReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit an existing review. Only the review author can edit it."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own reviews")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(review, key, value)

    db.commit()
    db.refresh(review)
    return review


# ──────────────────────────────────────────────
# DELETE REVIEW
# ──────────────────────────────────────────────

@router.delete("/{review_id}")
def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a review. Author or admin can delete."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if current_user.role != "admin" and review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own reviews")

    db.delete(review)
    db.commit()
    return {"message": "Review deleted successfully"}


# ──────────────────────────────────────────────
# ADMIN: TOGGLE VISIBILITY
# ──────────────────────────────────────────────

@router.put("/{review_id}/toggle-visibility")
def toggle_review_visibility(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Admin toggles a review's visibility.
    Use this to hide spam, abusive, or fake reviews without permanently deleting them.
    """
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_visible = not review.is_visible
    db.commit()

    action = "visible" if review.is_visible else "hidden"
    logger.info(f"Admin {current_user.id} marked review {review_id} as {action}")
    return {"message": f"Review is now {action}", "is_visible": review.is_visible}
