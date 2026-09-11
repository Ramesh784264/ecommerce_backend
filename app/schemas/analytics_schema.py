"""
Admin Analytics Schemas

All response models for the analytics dashboard endpoints.
Uses plain Pydantic models — no ORM mapping needed (pure aggregation queries).
"""

from pydantic import BaseModel
from typing import Optional
from datetime import date


# ── DASHBOARD SUMMARY ─────────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    """Single-call snapshot of the entire store's KPIs."""
    total_users: int
    total_vendors: int
    total_products: int
    total_categories: int
    total_orders: int
    total_revenue: float           # Sum of all paid order amounts
    pending_orders: int
    orders_today: int
    revenue_today: float
    pending_vendor_requests: int
    low_stock_products: int        # Products with stock <= 5


# ── REVENUE REPORT ────────────────────────────────────────────────────────────

class DailyRevenue(BaseModel):
    """Revenue aggregated per day."""
    date: str                      # ISO date string "2026-09-10"
    orders: int
    revenue: float


class RevenueReport(BaseModel):
    period: str                    # "daily" | "weekly" | "monthly"
    from_date: str
    to_date: str
    total_revenue: float
    total_orders: int
    data: list[DailyRevenue]


# ── TOP PRODUCTS ──────────────────────────────────────────────────────────────

class TopProduct(BaseModel):
    product_id: int
    product_name: str
    category_name: str
    vendor_id: int
    total_quantity_sold: int
    total_revenue: float
    current_stock: int


# ── ORDER STATUS BREAKDOWN ────────────────────────────────────────────────────

class OrderStatusBreakdown(BaseModel):
    status: str
    count: int
    percentage: float


class OrderAnalytics(BaseModel):
    total_orders: int
    breakdown: list[OrderStatusBreakdown]
    payment_breakdown: list[OrderStatusBreakdown]   # by payment_status


# ── USER GROWTH ───────────────────────────────────────────────────────────────

class DailyUserGrowth(BaseModel):
    date: str
    new_users: int
    cumulative_users: int


# ── LOW STOCK ─────────────────────────────────────────────────────────────────

class LowStockProduct(BaseModel):
    product_id: int
    product_name: str
    category_name: str
    vendor_name: str
    current_stock: int
    price: float


# ── COUPON STATS ──────────────────────────────────────────────────────────────

class CouponStats(BaseModel):
    coupon_id: int
    code: str
    discount_type: str
    discount_value: float
    total_used: int
    total_discount_given: float
    is_active: bool


# ── VENDOR PERFORMANCE ────────────────────────────────────────────────────────

class VendorPerformance(BaseModel):
    vendor_id: int
    vendor_name: str
    shop_name: str
    total_products: int
    total_orders: int
    total_revenue: float
    average_rating: float
