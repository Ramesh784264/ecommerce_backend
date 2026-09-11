"""
Application entry point.

Changes from initial version:
  - Added CORS middleware (required for browser clients)
  - Added global exception handler (prevents raw stack traces leaking to clients)
  - Added /api/v1 prefix to all routers
  - Added lifespan events for startup/shutdown logging
  - Registered payment router and payment_model
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.database import Base, engine
from app.models import (
    cart_model,
    category_model,
    coupon_model,   # NEW
    order_model,
    payment_model,
    product_model,
    review_model,   # NEW
    user_model,
    vendor_model,
    wishlist_model,
)
from app.routes import auth, category, product, vendor, admin, cart, wishlist, order
from app.routes import payment     # Razorpay
from app.routes import otp         # OTP & Password Reset
from app.routes import review      # Reviews & Ratings
from app.routes import coupon      # Coupons & Discounts
from app.routes import analytics   # Admin Analytics Dashboard & Reports
from app.routes import ws          # Real-time WebSocket connection & events
from app.routes import ai          # AI Recommendations, Smart Search & Chatbot

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("[STARTUP] E-Commerce API starting up...")
    Base.metadata.create_all(bind=engine)
    logger.info("[SUCCESS] Database tables verified/created")
    yield
    logger.info("[SHUTDOWN] E-Commerce API shutting down")


app = FastAPI(
    title="E-Commerce API",
    version="1.0.0",
    description="Production-grade FastAPI + MySQL e-commerce backend",
    lifespan=lifespan,
)

# ── CORS Middleware ──────────────────────────────────────────────────────────
# In production, replace "*" with your actual frontend domain(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # e.g., ["https://yourstore.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global Exception Handler ─────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all handler so internal errors never expose stack traces to clients.
    All unhandled exceptions are logged server-side and return a generic 500.
    """
    logger.error(f"Unhandled exception on {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."},
    )


# ── Routers ──────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth.router,      prefix=API_PREFIX)
app.include_router(category.router,  prefix=API_PREFIX)
app.include_router(product.router,   prefix=API_PREFIX)
app.include_router(vendor.router,    prefix=API_PREFIX)
app.include_router(admin.router,     prefix=API_PREFIX)
app.include_router(cart.router,      prefix=API_PREFIX)
app.include_router(wishlist.router,  prefix=API_PREFIX)
app.include_router(order.router,     prefix=API_PREFIX)
app.include_router(payment.router,   prefix=API_PREFIX)
app.include_router(otp.router,       prefix=API_PREFIX)   # OTP & Password Reset
app.include_router(review.router,    prefix=API_PREFIX)   # Reviews & Ratings
app.include_router(coupon.router,    prefix=API_PREFIX)   # Coupons & Discounts
app.include_router(analytics.router, prefix=API_PREFIX)   # Admin Analytics
app.include_router(ws.router,        prefix=API_PREFIX)   # Real-time WebSockets
app.include_router(ai.router,        prefix=API_PREFIX)   # AI Recommendations, Search & Bot


@app.get("/")
def root():
    return {
        "message": "E-Commerce API running successfully",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    """Used by load balancers and uptime monitors."""
    return {"status": "healthy"}
