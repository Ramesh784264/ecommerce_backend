"""
Admin Analytics Routes

All endpoints are /admin/analytics/* and require admin role.

Endpoints:
  GET /admin/analytics/dashboard        → Full KPI snapshot
  GET /admin/analytics/revenue          → Revenue report (daily/weekly/monthly)
  GET /admin/analytics/top-products     → Best-selling products by qty or revenue
  GET /admin/analytics/orders           → Order status & payment breakdown
  GET /admin/analytics/user-growth      → New user registrations over time
  GET /admin/analytics/low-stock        → Products with low inventory
  GET /admin/analytics/coupons          → Coupon usage statistics
  GET /admin/analytics/vendors          → Vendor performance leaderboard

All queries use raw SQLAlchemy aggregations — no extra tables needed.
Indexes already on: Order.status, Order.payment_status, Order.created_at,
                    Product.is_active, User.role, CartItem.user_id
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.cart_model import CartItem
from app.models.category_model import Category
from app.models.coupon_model import Coupon, CouponUsage
from app.models.order_model import Order, OrderItem
from app.models.product_model import Product
from app.models.review_model import Review
from app.models.user_model import User
from app.models.vendor_model import VendorProfile
from app.schemas.analytics_schema import (
    CouponStats,
    DailyRevenue,
    DailyUserGrowth,
    DashboardSummary,
    LowStockProduct,
    OrderAnalytics,
    OrderStatusBreakdown,
    RevenueReport,
    TopProduct,
    VendorPerformance,
)
from app.utils.dependencies import role_required

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/analytics", tags=["Admin Analytics"])

LOW_STOCK_THRESHOLD = 5   # Products with stock <= this are flagged


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — date boundary
# ─────────────────────────────────────────────────────────────────────────────

def _today_start() -> datetime:
    today = date.today()
    return datetime(today.year, today.month, today.day, 0, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 1. DASHBOARD SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Single-call KPI snapshot for the admin home screen.
    All aggregations are done in parallel SQL queries.
    """
    today = _today_start()

    total_users      = db.query(func.count(User.id)).filter(User.role == "customer").scalar() or 0
    total_vendors    = db.query(func.count(User.id)).filter(User.role == "vendor").scalar() or 0
    total_products   = db.query(func.count(Product.id)).filter(Product.is_active == True).scalar() or 0
    total_categories = db.query(func.count(Category.id)).filter(Category.is_active == True).scalar() or 0
    total_orders     = db.query(func.count(Order.id)).scalar() or 0

    total_revenue = float(
        db.query(func.sum(Order.total_amount))
        .filter(Order.payment_status == "paid")
        .scalar() or 0
    )

    pending_orders = (
        db.query(func.count(Order.id)).filter(Order.status == "pending").scalar() or 0
    )

    orders_today = (
        db.query(func.count(Order.id)).filter(Order.created_at >= today).scalar() or 0
    )

    revenue_today = float(
        db.query(func.sum(Order.total_amount))
        .filter(Order.payment_status == "paid", Order.created_at >= today)
        .scalar() or 0
    )

    pending_vendor_requests = (
        db.query(func.count(VendorProfile.id))
        .filter(VendorProfile.status == "pending")
        .scalar() or 0
    )

    low_stock_products = (
        db.query(func.count(Product.id))
        .filter(Product.is_active == True, Product.stock <= LOW_STOCK_THRESHOLD)
        .scalar() or 0
    )

    return DashboardSummary(
        total_users=total_users,
        total_vendors=total_vendors,
        total_products=total_products,
        total_categories=total_categories,
        total_orders=total_orders,
        total_revenue=round(total_revenue, 2),
        pending_orders=pending_orders,
        orders_today=orders_today,
        revenue_today=round(revenue_today, 2),
        pending_vendor_requests=pending_vendor_requests,
        low_stock_products=low_stock_products,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. REVENUE REPORT
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/revenue", response_model=RevenueReport)
def get_revenue_report(
    period: str = Query("daily", description="'daily' | 'weekly' | 'monthly'"),
    from_date: Optional[date] = Query(None, description="Start date (defaults to 30 days ago)"),
    to_date: Optional[date] = Query(None, description="End date (defaults to today)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Revenue aggregated by day, week, or month.
    Only counts PAID orders.

    Example queries:
      /admin/analytics/revenue?period=daily&from_date=2026-09-01&to_date=2026-09-30
      /admin/analytics/revenue?period=monthly
    """
    # Default date range: last 30 days
    end   = to_date   or date.today()
    start = from_date or (end - timedelta(days=29))

    start_dt = datetime(start.year, start.month, start.day, 0, 0, 0)
    end_dt   = datetime(end.year, end.month, end.day, 23, 59, 59)

    # Fetch all paid orders in range
    orders = (
        db.query(Order.created_at, Order.total_amount)
        .filter(
            Order.payment_status == "paid",
            Order.created_at >= start_dt,
            Order.created_at <= end_dt,
        )
        .all()
    )

    # Aggregate by chosen period
    buckets: dict[str, dict] = {}

    for created_at, amount in orders:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        if period == "weekly":
            # ISO week start (Monday)
            iso_week_start = created_at - timedelta(days=created_at.weekday())
            key = iso_week_start.strftime("%Y-%m-%d")
        elif period == "monthly":
            key = created_at.strftime("%Y-%m")
        else:  # daily
            key = created_at.strftime("%Y-%m-%d")

        if key not in buckets:
            buckets[key] = {"date": key, "orders": 0, "revenue": 0.0}
        buckets[key]["orders"] += 1
        buckets[key]["revenue"] += float(amount)

    # Fill missing days with zero (for clean charts)
    if period == "daily":
        current = start
        while current <= end:
            key = current.strftime("%Y-%m-%d")
            if key not in buckets:
                buckets[key] = {"date": key, "orders": 0, "revenue": 0.0}
            current += timedelta(days=1)

    sorted_data = sorted(buckets.values(), key=lambda x: x["date"])
    data = [DailyRevenue(**row) for row in sorted_data]

    total_revenue = round(sum(r.revenue for r in data), 2)
    total_orders  = sum(r.orders for r in data)

    return RevenueReport(
        period=period,
        from_date=str(start),
        to_date=str(end),
        total_revenue=total_revenue,
        total_orders=total_orders,
        data=data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. TOP-SELLING PRODUCTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/top-products", response_model=list[TopProduct])
def get_top_products(
    limit: int = Query(10, ge=1, le=50, description="Number of products to return"),
    sort_by: str = Query("quantity", description="'quantity' | 'revenue'"),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Top-selling products by total quantity sold or by total revenue.
    Only counts delivered/confirmed orders to reflect actual sales.
    """
    query = (
        db.query(
            Product.id,
            Product.name,
            Category.name.label("category_name"),
            Product.vendor_id,
            func.sum(OrderItem.quantity).label("total_qty"),
            func.sum(OrderItem.quantity * OrderItem.price_at_purchase).label("total_rev"),
            Product.stock,
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Category, Category.id == Product.category_id)
        .filter(Order.status.in_(["confirmed", "shipped", "delivered"]))
    )

    if from_date:
        query = query.filter(Order.created_at >= datetime(from_date.year, from_date.month, from_date.day))
    if to_date:
        query = query.filter(Order.created_at <= datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59))

    query = query.group_by(Product.id, Product.name, Category.name, Product.vendor_id, Product.stock)

    if sort_by == "revenue":
        query = query.order_by(func.sum(OrderItem.quantity * OrderItem.price_at_purchase).desc())
    else:
        query = query.order_by(func.sum(OrderItem.quantity).desc())

    rows = query.limit(limit).all()

    return [
        TopProduct(
            product_id=row.id,
            product_name=row.name,
            category_name=row.category_name,
            vendor_id=row.vendor_id,
            total_quantity_sold=int(row.total_qty or 0),
            total_revenue=round(float(row.total_rev or 0), 2),
            current_stock=row.stock,
        )
        for row in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 4. ORDER ANALYTICS (Status & Payment Breakdown)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/orders", response_model=OrderAnalytics)
def get_order_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Returns a breakdown of orders by status and by payment status.
    Ideal for pie/donut charts in the admin dashboard.
    """
    total_orders = db.query(func.count(Order.id)).scalar() or 0

    # Status breakdown
    status_rows = (
        db.query(Order.status, func.count(Order.id).label("cnt"))
        .group_by(Order.status)
        .all()
    )

    status_breakdown = [
        OrderStatusBreakdown(
            status=row.status,
            count=row.cnt,
            percentage=round((row.cnt / total_orders * 100) if total_orders else 0, 1),
        )
        for row in status_rows
    ]

    # Payment breakdown
    payment_rows = (
        db.query(Order.payment_status, func.count(Order.id).label("cnt"))
        .group_by(Order.payment_status)
        .all()
    )

    payment_breakdown = [
        OrderStatusBreakdown(
            status=row.payment_status,
            count=row.cnt,
            percentage=round((row.cnt / total_orders * 100) if total_orders else 0, 1),
        )
        for row in payment_rows
    ]

    return OrderAnalytics(
        total_orders=total_orders,
        breakdown=status_breakdown,
        payment_breakdown=payment_breakdown,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. USER GROWTH
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/user-growth", response_model=list[DailyUserGrowth])
def get_user_growth(
    days: int = Query(30, ge=7, le=365, description="Number of days to look back"),
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    New user registrations per day for the last N days.
    Includes cumulative total for trend line charts.
    """
    start_dt = datetime.now(timezone.utc) - timedelta(days=days)

    # Count all users created before start for cumulative baseline
    baseline = (
        db.query(func.count(User.id))
        .filter(User.created_at < start_dt, User.role == "customer")
        .scalar() or 0
    )

    rows = (
        db.query(
            func.date(User.created_at).label("reg_date"),
            func.count(User.id).label("new_users"),
        )
        .filter(User.created_at >= start_dt, User.role == "customer")
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at))
        .all()
    )

    result = []
    cumulative = baseline
    for row in rows:
        cumulative += row.new_users
        result.append(
            DailyUserGrowth(
                date=str(row.reg_date),
                new_users=row.new_users,
                cumulative_users=cumulative,
            )
        )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 6. LOW STOCK ALERTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/low-stock", response_model=list[LowStockProduct])
def get_low_stock(
    threshold: int = Query(5, ge=0, le=100, description="Stock level considered 'low'"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Products with stock at or below the threshold.
    Default threshold: 5 units.
    """
    rows = (
        db.query(
            Product.id,
            Product.name,
            Category.name.label("cat_name"),
            User.name.label("vendor_name"),
            Product.stock,
            Product.price,
        )
        .join(Category, Category.id == Product.category_id)
        .join(User, User.id == Product.vendor_id)
        .filter(Product.is_active == True, Product.stock <= threshold)
        .order_by(Product.stock.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        LowStockProduct(
            product_id=row.id,
            product_name=row.name,
            category_name=row.cat_name,
            vendor_name=row.vendor_name,
            current_stock=row.stock,
            price=float(row.price),
        )
        for row in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 7. COUPON STATISTICS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/coupons", response_model=list[CouponStats])
def get_coupon_stats(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Usage stats for all coupons — sorted by total discount given (most expensive first).
    """
    rows = (
        db.query(
            Coupon.id,
            Coupon.code,
            Coupon.discount_type,
            Coupon.discount_value,
            Coupon.used_count,
            Coupon.is_active,
            func.coalesce(func.sum(CouponUsage.discount_applied), 0).label("total_discount"),
        )
        .outerjoin(CouponUsage, CouponUsage.coupon_id == Coupon.id)
        .group_by(
            Coupon.id, Coupon.code, Coupon.discount_type,
            Coupon.discount_value, Coupon.used_count, Coupon.is_active,
        )
        .order_by(func.coalesce(func.sum(CouponUsage.discount_applied), 0).desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        CouponStats(
            coupon_id=row.id,
            code=row.code,
            discount_type=row.discount_type,
            discount_value=float(row.discount_value),
            total_used=row.used_count,
            total_discount_given=round(float(row.total_discount), 2),
            is_active=row.is_active,
        )
        for row in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 8. VENDOR PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/vendors", response_model=list[VendorPerformance])
def get_vendor_performance(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Vendor leaderboard: total products, orders, revenue, and average rating.
    Sorted by total revenue (highest earner first).
    """
    rows = (
        db.query(
            User.id.label("vendor_id"),
            User.name.label("vendor_name"),
            VendorProfile.shop_name,
            func.count(Product.id.distinct()).label("total_products"),
            func.count(OrderItem.id.distinct()).label("total_order_items"),
            func.coalesce(
                func.sum(OrderItem.quantity * OrderItem.price_at_purchase), 0
            ).label("total_revenue"),
            func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
        )
        .join(VendorProfile, VendorProfile.user_id == User.id)
        .outerjoin(Product, Product.vendor_id == User.id)
        .outerjoin(OrderItem, OrderItem.product_id == Product.id)
        .outerjoin(Review, Review.product_id == Product.id)
        .filter(User.role == "vendor")
        .group_by(User.id, User.name, VendorProfile.shop_name)
        .order_by(
            func.coalesce(func.sum(OrderItem.quantity * OrderItem.price_at_purchase), 0).desc()
        )
        .limit(limit)
        .all()
    )

    return [
        VendorPerformance(
            vendor_id=row.vendor_id,
            vendor_name=row.vendor_name,
            shop_name=row.shop_name,
            total_products=row.total_products or 0,
            total_orders=row.total_order_items or 0,
            total_revenue=round(float(row.total_revenue), 2),
            average_rating=round(float(row.avg_rating), 1),
        )
        for row in rows
    ]
