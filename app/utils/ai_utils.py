"""
AI Utility Functions

Implements three AI features WITHOUT external API costs (no OpenAI required):

1. Product Recommendations
   - Collaborative filtering: "users who bought X also bought Y"
   - Category-based fallback if no order history

2. Smart Product Search
   - Fuzzy string matching (handles typos like "iphon" → "iPhone")
   - Synonym expansion ("mobile" → "phone", "laptop" → "notebook")
   - Weighted relevance scoring (name match > description match > category match)

3. Rule-Based Chatbot
   - Pattern-matching FAQ engine
   - Handles: order status, returns, shipping, payments, account, products
   - Graceful "I don't know" fallback

Production upgrade path:
  - Recommendations: Replace with a proper ALS/SVD matrix factorization model
  - Search: Replace with Elasticsearch or Typesense for full-text + vector search
  - Chatbot: Plug in OpenAI/Gemini API — the request/response schema stays the same
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. COLLABORATIVE FILTERING — Purchase-based Recommendations
# ─────────────────────────────────────────────────────────────────────────────

def get_recommendations(
    user_id: int,
    db,
    limit: int = 10,
) -> list[dict]:
    """
    Returns product recommendations for a user.

    Strategy (in order of preference):
      A) Collaborative filtering: find products bought by users who share
         purchase history with the current user
      B) Category-based: if user has purchases, recommend more from the same categories
      C) Popularity fallback: top-reviewed, in-stock products (for new users)
    """
    from app.models.order_model import Order, OrderItem
    from app.models.product_model import Product
    from app.models.category_model import Category
    from app.models.review_model import Review
    from sqlalchemy import func

    # Get current user's purchased product IDs
    user_orders = (
        db.query(Order.id)
        .filter(Order.user_id == user_id, Order.status.in_(["confirmed", "shipped", "delivered"]))
        .subquery()
    )

    user_product_ids = (
        db.query(OrderItem.product_id)
        .filter(OrderItem.order_id.in_(user_orders))
        .all()
    )
    user_product_ids = {row[0] for row in user_product_ids}

    if user_product_ids:
        # Strategy A: Collaborative filtering
        # Find other users who bought any of the same products
        similar_user_orders = (
            db.query(Order.user_id)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .filter(
                OrderItem.product_id.in_(user_product_ids),
                Order.user_id != user_id,
            )
            .distinct()
            .subquery()
        )

        # Get products bought by those similar users that current user hasn't bought
        collab_products = (
            db.query(
                Product,
                func.count(OrderItem.id).label("buy_count"),
                func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
            )
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(Review, Review.product_id == Product.id)
            .filter(
                Order.user_id.in_(similar_user_orders),
                Product.id.notin_(user_product_ids),
                Product.is_active == True,
                Product.stock > 0,
            )
            .group_by(Product.id)
            .order_by(func.count(OrderItem.id).desc(), func.avg(Review.rating).desc())
            .limit(limit)
            .all()
        )

        if collab_products:
            return [
                {
                    "product_id": row.Product.id,
                    "name": row.Product.name,
                    "price": float(row.Product.price),
                    "stock": row.Product.stock,
                    "image_url": row.Product.image_url,
                    "avg_rating": round(float(row.avg_rating), 1),
                    "reason": "Customers who bought similar products also liked this",
                }
                for row in collab_products
            ]

        # Strategy B: Category-based
        user_categories = (
            db.query(Product.category_id)
            .filter(Product.id.in_(user_product_ids))
            .distinct()
            .all()
        )
        cat_ids = [c[0] for c in user_categories]

        cat_products = (
            db.query(
                Product,
                func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
            )
            .outerjoin(Review, Review.product_id == Product.id)
            .filter(
                Product.category_id.in_(cat_ids),
                Product.id.notin_(user_product_ids),
                Product.is_active == True,
                Product.stock > 0,
            )
            .group_by(Product.id)
            .order_by(func.avg(Review.rating).desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "product_id": row.Product.id,
                "name": row.Product.name,
                "price": float(row.Product.price),
                "stock": row.Product.stock,
                "image_url": row.Product.image_url,
                "avg_rating": round(float(row.avg_rating), 1),
                "reason": "Based on your previous purchases",
            }
            for row in cat_products
        ]

    # Strategy C: Popularity fallback (new users)
    popular = (
        db.query(
            Product,
            func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
            func.count(Review.id).label("review_count"),
        )
        .outerjoin(Review, Review.product_id == Product.id)
        .filter(Product.is_active == True, Product.stock > 0)
        .group_by(Product.id)
        .order_by(
            func.coalesce(func.avg(Review.rating), 0).desc(),
            func.count(Review.id).desc(),
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "product_id": row.Product.id,
            "name": row.Product.name,
            "price": float(row.Product.price),
            "stock": row.Product.stock,
            "image_url": row.Product.image_url,
            "avg_rating": round(float(row.avg_rating), 1),
            "reason": "Popular & highly rated",
        }
        for row in popular
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 2. SMART SEARCH — Fuzzy + Synonym + Weighted Scoring
# ─────────────────────────────────────────────────────────────────────────────

# Synonym dictionary — expand these as needed
_SYNONYMS: dict[str, list[str]] = {
    "mobile": ["phone", "smartphone", "cellphone"],
    "phone": ["mobile", "smartphone", "cellphone"],
    "laptop": ["notebook", "computer", "pc"],
    "notebook": ["laptop", "computer", "pc"],
    "tv": ["television", "monitor", "display", "screen"],
    "headphones": ["earphones", "earbuds", "headset"],
    "shirt": ["tshirt", "top", "blouse"],
    "shoes": ["sneakers", "footwear", "boots", "sandals"],
    "bag": ["backpack", "purse", "handbag", "tote"],
    "watch": ["smartwatch", "wristwatch", "timepiece"],
}


def _fuzzy_score(query: str, text: str) -> float:
    """Returns similarity ratio between 0.0 and 1.0."""
    return SequenceMatcher(None, query.lower(), text.lower()).ratio()


def _get_synonyms(word: str) -> list[str]:
    return _SYNONYMS.get(word.lower(), [])


def smart_search(
    query: str,
    db,
    category_id: Optional[int] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_rating: Optional[float] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Multi-signal product search:
      1. Exact name match (score = 1.0)
      2. Starts-with match (score = 0.9)
      3. Contains match (score = 0.8)
      4. Fuzzy name match > 0.6 (score = ratio)
      5. Category/description match (score = 0.5)
      6. Synonym expansion for all above

    Only active, in-stock products returned.
    Results sorted by score desc, then avg rating desc.
    """
    from app.models.product_model import Product
    from app.models.review_model import Review
    from app.models.category_model import Category
    from sqlalchemy import func

    q = query.strip().lower()
    words = q.split()
    expanded_words = set(words)
    for word in words:
        expanded_words.update(_get_synonyms(word))

    # Fetch candidate products from DB (do broad filter, then score in Python)
    db_query = (
        db.query(
            Product,
            Category.name.label("cat_name"),
            func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
        )
        .join(Category, Category.id == Product.category_id)
        .outerjoin(Review, Review.product_id == Product.id)
        .filter(Product.is_active == True, Product.stock > 0)
    )

    if category_id:
        db_query = db_query.filter(Product.category_id == category_id)
    if min_price is not None:
        db_query = db_query.filter(Product.price >= min_price)
    if max_price is not None:
        db_query = db_query.filter(Product.price <= max_price)

    db_query = db_query.group_by(Product.id, Category.name)
    candidates = db_query.all()

    scored = []
    for row in candidates:
        product = row.Product
        avg_rating = float(row.avg_rating)

        if min_rating and avg_rating < min_rating:
            continue

        name_lower = product.name.lower()
        desc_lower = (product.description or "").lower()
        cat_lower = row.cat_name.lower()

        score = 0.0

        for word in expanded_words:
            # Exact name match
            if q == name_lower:
                score = max(score, 1.0)
            # Starts with query
            elif name_lower.startswith(q):
                score = max(score, 0.9)
            # Name contains any expanded word
            elif word in name_lower:
                score = max(score, 0.85)
            # Fuzzy name match
            else:
                fuzzy = _fuzzy_score(word, name_lower)
                if fuzzy > 0.6:
                    score = max(score, fuzzy * 0.8)

            # Description / category bonus
            if word in desc_lower:
                score = max(score, 0.5)
            if word in cat_lower:
                score = max(score, 0.4)

        if score > 0.3:   # Relevance threshold — tune this
            scored.append({
                "product_id": product.id,
                "name": product.name,
                "description": product.description,
                "price": float(product.price),
                "stock": product.stock,
                "category": row.cat_name,
                "image_url": product.image_url,
                "avg_rating": round(avg_rating, 1),
                "relevance_score": round(score, 3),
            })

    # Sort: relevance first, then rating
    scored.sort(key=lambda x: (x["relevance_score"], x["avg_rating"]), reverse=True)
    return scored[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# 3. RULE-BASED CHATBOT — Pattern Matching FAQ Engine
# ─────────────────────────────────────────────────────────────────────────────

# Each rule: (compiled_regex_pattern, response_text)
_CHAT_RULES: list[tuple] = [
    # Greetings
    (re.compile(r"\b(hi|hello|hey|good morning|good evening|howdy)\b", re.I),
     "👋 Hello! I'm ShopEase's virtual assistant. I can help you with orders, payments, returns, shipping, and more. What can I help you with?"),

    # Order tracking
    (re.compile(r"\b(track|where|status).*(order|parcel|package|delivery)\b", re.I),
     "📦 To track your order, log in and go to **My Orders**. You can see the real-time status there. You'll also receive an email update whenever your order status changes."),

    # Cancellation
    (re.compile(r"\b(cancel|cancellation).*(order)\b", re.I),
     "❌ You can cancel an order from **My Orders** before it's shipped. Once shipped, you'll need to use our return/refund process. Need help with a specific order ID?"),

    # Returns
    (re.compile(r"\b(return|refund|exchange|replace)\b", re.I),
     "🔄 We accept returns within 7 days of delivery for most items. Go to **My Orders → Request Return**. Refunds are processed within 5–7 business days to your original payment method."),

    # Payment issues
    (re.compile(r"\b(payment|pay|transaction|razorpay|failed|declined|charged)\b", re.I),
     "💳 For payment issues, check if your bank has flagged the transaction. If money was deducted but the order wasn't placed, it will be auto-refunded within 5–7 business days. Contact us with your transaction ID for faster resolution."),

    # Shipping / delivery time
    (re.compile(r"\b(shipping|deliver|dispatch|arrive|how long|when will)\b", re.I),
     "🚚 Standard delivery takes 3–7 business days. Express delivery (1–2 days) is available at checkout for select locations. You'll receive a tracking number once your order ships."),

    # COD
    (re.compile(r"\b(cod|cash on delivery|pay on delivery)\b", re.I),
     "💰 Yes, Cash on Delivery is available for most pin codes. You'll see the COD option at checkout if it's available for your location."),

    # Coupon / discount
    (re.compile(r"\b(coupon|promo|discount|offer|code|voucher)\b", re.I),
     "🏷️ Enter your coupon code at the checkout page in the **Coupon Code** field. The discount will be applied automatically. Codes are case-insensitive."),

    # Account / login
    (re.compile(r"\b(account|login|sign in|password|forgot password|reset)\b", re.I),
     "🔐 Forgot your password? Use the **Forgot Password** option on the login page. An OTP will be sent to your registered email. If you need more help, contact support@shopease.com."),

    # Seller / vendor
    (re.compile(r"\b(sell|vendor|seller|list products|become a seller)\b", re.I),
     "🏪 Interested in selling on ShopEase? Go to **Become a Vendor** and fill out your shop details. Our team will review your application within 2 business days."),

    # Contact
    (re.compile(r"\b(contact|support|help|human|agent|representative)\b", re.I),
     "📞 You can reach our support team at **support@shopease.com** or call **1800-123-4567** (9 AM – 9 PM IST, Mon–Sat). We typically respond within 24 hours."),

    # Product availability
    (re.compile(r"\b(available|stock|out of stock|in stock)\b", re.I),
     "🛍️ Product availability is shown on the product page. If an item is out of stock, you can add it to your **Wishlist** and we'll notify you when it's back."),

    # Thanks
    (re.compile(r"\b(thank|thanks|thank you|thx)\b", re.I),
     "😊 You're welcome! Is there anything else I can help you with?"),

    # Goodbye
    (re.compile(r"\b(bye|goodbye|see you|take care)\b", re.I),
     "👋 Goodbye! Have a great shopping experience at ShopEase!"),
]

_FALLBACK = (
    "🤔 I'm not sure I understood that. I can help with:\n"
    "- 📦 Order tracking & cancellation\n"
    "- 🔄 Returns & refunds\n"
    "- 💳 Payment issues\n"
    "- 🚚 Shipping & delivery\n"
    "- 🏷️ Coupons & discounts\n"
    "- 🔐 Account & password\n\n"
    "Or type **contact** to reach a human agent."
)


def chatbot_respond(message: str) -> str:
    """
    Match user message against rule patterns and return the best response.
    Falls back to the generic help menu if no rule matches.
    """
    if not message or not message.strip():
        return _FALLBACK

    message = message.strip()

    for pattern, response in _CHAT_RULES:
        if pattern.search(message):
            logger.debug(f"Chatbot matched pattern: {pattern.pattern!r}")
            return response

    logger.debug(f"Chatbot no match for: {message!r}")
    return _FALLBACK
