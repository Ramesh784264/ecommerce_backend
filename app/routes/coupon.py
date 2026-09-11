"""
Coupons & Discounts Routes

Endpoints:
  POST  /coupons/                    → Admin: Create coupon
  GET   /coupons/                    → Admin: List all coupons
  GET   /coupons/{coupon_id}         → Admin: Get coupon details
  PUT   /coupons/{coupon_id}         → Admin: Update coupon
  DELETE /coupons/{coupon_id}        → Admin: Delete coupon
  POST  /coupons/apply               → Customer: Validate & preview discount
  GET   /coupons/my-usage            → Customer: View own coupon usage history

Business Rules:
  - Coupon code is case-insensitive (normalized to uppercase)
  - Only active, non-expired coupons with remaining uses can be applied
  - User cannot exceed max_uses_per_user
  - For percentage coupons, max_discount_amount acts as a cap
  - Coupon usage is recorded in coupon_usages table (linked to order at checkout)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.coupon_model import Coupon, CouponUsage
from app.models.user_model import User
from app.schemas.coupon_schema import (
    CouponApplyRequest,
    CouponApplyResponse,
    CouponCreate,
    CouponResponse,
    CouponUpdate,
)
from app.utils.dependencies import get_current_user, role_required

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coupons", tags=["Coupons & Discounts"])


# ──────────────────────────────────────────────
# SHARED HELPER — Calculate discount amount
# ──────────────────────────────────────────────

def _calculate_discount(coupon: Coupon, order_amount: float) -> float:
    """
    Calculate the actual discount in INR.

    For percentage:  discount = order_amount * (discount_value / 100)
                     capped at max_discount_amount if set
    For fixed:       discount = min(discount_value, order_amount)  (can't exceed order total)
    """
    if coupon.discount_type == "percentage":
        raw_discount = order_amount * (float(coupon.discount_value) / 100)
        if coupon.max_discount_amount:
            raw_discount = min(raw_discount, float(coupon.max_discount_amount))
    else:  # fixed
        raw_discount = min(float(coupon.discount_value), order_amount)

    return round(raw_discount, 2)


def _validate_coupon_eligibility(
    coupon: Coupon, user_id: int, order_amount: float, db: Session
) -> None:
    """
    Raises HTTPException if the coupon cannot be applied.
    Checks: active, expired, usage limits, per-user limits, min order amount.
    """
    if not coupon.is_active:
        raise HTTPException(status_code=400, detail="This coupon is not active")

    if coupon.expires_at:
        expiry = coupon.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expiry:
            raise HTTPException(status_code=400, detail="This coupon has expired")

    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        raise HTTPException(status_code=400, detail="This coupon has reached its usage limit")

    if order_amount < float(coupon.min_order_amount):
        raise HTTPException(
            status_code=400,
            detail=f"Minimum order amount for this coupon is ₹{coupon.min_order_amount:.2f}. "
                   f"Your cart total is ₹{order_amount:.2f}.",
        )

    # Check per-user usage
    user_usage_count = (
        db.query(CouponUsage)
        .filter(CouponUsage.coupon_id == coupon.id, CouponUsage.user_id == user_id)
        .count()
    )
    if user_usage_count >= coupon.max_uses_per_user:
        raise HTTPException(
            status_code=400,
            detail=f"You have already used this coupon {user_usage_count} time(s). "
                   f"Maximum {coupon.max_uses_per_user} use(s) per user.",
        )


# ──────────────────────────────────────────────
# ADMIN: CREATE COUPON
# ──────────────────────────────────────────────

@router.post("/", response_model=CouponResponse)
def create_coupon(
    data: CouponCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """Admin creates a new coupon code."""
    existing = db.query(Coupon).filter(Coupon.code == data.code.upper()).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Coupon code '{data.code}' already exists",
        )

    # Validate percentage discount value
    if data.discount_type == "percentage" and data.discount_value > 100:
        raise HTTPException(
            status_code=400, detail="Percentage discount cannot exceed 100%"
        )

    coupon = Coupon(
        code=data.code.upper(),
        description=data.description,
        discount_type=data.discount_type,
        discount_value=data.discount_value,
        min_order_amount=data.min_order_amount,
        max_discount_amount=data.max_discount_amount,
        max_uses=data.max_uses,
        max_uses_per_user=data.max_uses_per_user,
        is_active=data.is_active,
        expires_at=data.expires_at,
    )
    db.add(coupon)
    db.commit()
    db.refresh(coupon)

    logger.info(f"Coupon created: {coupon.code} by admin {current_user.id}")
    return coupon


# ──────────────────────────────────────────────
# ADMIN: LIST ALL COUPONS
# ──────────────────────────────────────────────

@router.get("/", response_model=list[CouponResponse])
def list_coupons(
    is_active: Optional[bool] = Query(None, description="Filter by active/inactive"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """Admin lists all coupons with optional active filter."""
    query = db.query(Coupon)
    if is_active is not None:
        query = query.filter(Coupon.is_active == is_active)
    return query.order_by(Coupon.created_at.desc()).offset(skip).limit(limit).all()


# ──────────────────────────────────────────────
# ADMIN: GET SINGLE COUPON
# ──────────────────────────────────────────────

@router.get("/{coupon_id}", response_model=CouponResponse)
def get_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return coupon


# ──────────────────────────────────────────────
# ADMIN: UPDATE COUPON
# ──────────────────────────────────────────────

@router.put("/{coupon_id}", response_model=CouponResponse)
def update_coupon(
    coupon_id: int,
    data: CouponUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(coupon, key, value)

    db.commit()
    db.refresh(coupon)
    logger.info(f"Coupon {coupon.code} updated by admin {current_user.id}")
    return coupon


# ──────────────────────────────────────────────
# ADMIN: DELETE COUPON
# ──────────────────────────────────────────────

@router.delete("/{coupon_id}")
def delete_coupon(
    coupon_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    db.delete(coupon)
    db.commit()
    logger.info(f"Coupon {coupon.code} deleted by admin {current_user.id}")
    return {"message": f"Coupon '{coupon.code}' deleted successfully"}


# ──────────────────────────────────────────────
# CUSTOMER: APPLY / VALIDATE COUPON
# ──────────────────────────────────────────────

@router.post("/apply", response_model=CouponApplyResponse)
def apply_coupon(
    data: CouponApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Validate a coupon code and return the discount preview.
    This does NOT record the usage — usage is recorded at /orders/checkout.

    Use this endpoint to show the discount amount in the cart UI before placing the order.
    """
    coupon = db.query(Coupon).filter(Coupon.code == data.code.upper()).first()

    if not coupon:
        raise HTTPException(status_code=404, detail=f"Coupon code '{data.code}' not found")

    # This raises HTTPException on any eligibility failure
    _validate_coupon_eligibility(coupon, current_user.id, data.order_amount, db)

    discount = _calculate_discount(coupon, data.order_amount)
    final_amount = round(data.order_amount - discount, 2)

    logger.info(
        f"Coupon applied: {coupon.code} by user {current_user.id}, "
        f"discount=₹{discount}, order=₹{data.order_amount}"
    )

    return CouponApplyResponse(
        valid=True,
        coupon_code=coupon.code,
        discount_type=coupon.discount_type,
        discount_value=float(coupon.discount_value),
        discount_applied=discount,
        original_amount=data.order_amount,
        final_amount=final_amount,
        message=f"Coupon '{coupon.code}' applied! You save ₹{discount:.2f}.",
    )


# ──────────────────────────────────────────────
# CUSTOMER: MY COUPON USAGE HISTORY
# ──────────────────────────────────────────────

from typing import Optional as _Opt
from datetime import datetime as _dt
from pydantic import BaseModel as _BaseModel


class CouponUsageHistoryResponse(_BaseModel):
    coupon_code: str
    discount_applied: float
    order_id: _Opt[int]
    used_at: _dt

    class Config:
        from_attributes = True


@router.get("/my-usage", response_model=list[CouponUsageHistoryResponse])
def my_coupon_usage(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """View the current user's coupon usage history."""
    usages = (
        db.query(CouponUsage)
        .filter(CouponUsage.user_id == current_user.id)
        .order_by(CouponUsage.used_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = []
    for usage in usages:
        result.append(
            CouponUsageHistoryResponse(
                coupon_code=usage.coupon.code,
                discount_applied=float(usage.discount_applied),
                order_id=usage.order_id,
                used_at=usage.used_at,
            )
        )
    return result

