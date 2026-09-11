"""
Razorpay utility functions.

Responsibilities:
- Create Razorpay orders
- Verify HMAC-SHA256 payment signature
- Trigger refunds
- Verify webhook signatures

All Razorpay credentials are read from environment variables — never hardcoded.
"""

import hashlib
import hmac
import json
import logging
import os

try:
    import razorpay
    import razorpay.errors
except ImportError:
    razorpay = None

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Razorpay client (singleton)
# ──────────────────────────────────────────────

def _get_razorpay_client():
    """
    Lazily initialise and return the Razorpay API client.
    Raises a 500 error if credentials are missing or library not installed,
    so the problem is surfaced immediately at the endpoint — not silently at import time.
    """
    if razorpay is None:
        logger.error("razorpay package is not installed. Run `pip install razorpay`.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment gateway package not installed on server. Please install razorpay.",
        )

    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        logger.error("RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET not set in environment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment gateway not configured. Contact support.",
        )

    return razorpay.Client(auth=(key_id, key_secret))


# ──────────────────────────────────────────────
# Public functions
# ──────────────────────────────────────────────

def create_razorpay_order(amount_inr: float, currency: str = "INR", receipt: str = "") -> dict:
    """
    Create a Razorpay order.

    Args:
        amount_inr: Total amount in Indian Rupees (e.g., 499.00)
        currency:   Currency code (default "INR")
        receipt:    A unique receipt string (e.g., our internal order ID as string)

    Returns:
        The Razorpay order dict containing `id`, `amount`, `currency`, etc.

    Raises:
        HTTPException(502): If the Razorpay API call fails.
    """
    client = _get_razorpay_client()

    # Razorpay expects amount in smallest currency unit (paise for INR)
    amount_paise = int(round(amount_inr * 100))

    try:
        razorpay_order = client.order.create(
            {
                "amount": amount_paise,
                "currency": currency,
                "receipt": receipt,
                "payment_capture": 1,  # Auto-capture on successful payment
            }
        )
        logger.info(f"Razorpay order created: {razorpay_order['id']} for receipt {receipt}")
        return razorpay_order

    except razorpay.errors.BadRequestError as e:
        logger.error(f"Razorpay BadRequest: {e}")
        raise HTTPException(status_code=400, detail=f"Razorpay error: {str(e)}")
    except Exception as e:
        logger.error(f"Razorpay order creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment gateway unavailable. Please try again.",
        )


def verify_payment_signature(
    razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str
) -> bool:
    """
    Verify the HMAC-SHA256 signature sent by Razorpay after payment.

    The signature is: HMAC_SHA256(razorpay_order_id + "|" + razorpay_payment_id, key_secret)

    Returns:
        True if signature matches, False otherwise.
    """
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")

    body = f"{razorpay_order_id}|{razorpay_payment_id}"
    expected_signature = hmac.new(
        key_secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_signature, razorpay_signature)

    if not is_valid:
        logger.warning(
            f"Signature mismatch for order {razorpay_order_id} / payment {razorpay_payment_id}"
        )

    return is_valid


def trigger_refund(razorpay_payment_id: str, amount_inr: float | None = None) -> dict:
    """
    Trigger a refund for a captured payment.

    Args:
        razorpay_payment_id: The Razorpay payment ID to refund
        amount_inr: Amount in INR to refund. If None, the full payment amount is refunded.

    Returns:
        Razorpay refund dict (contains `id`, `amount`, `status`, etc.)

    Raises:
        HTTPException(400): For Razorpay validation errors (e.g., already refunded)
        HTTPException(502): For gateway-level failures
    """
    client = _get_razorpay_client()

    refund_data = {}
    if amount_inr is not None:
        refund_data["amount"] = int(round(amount_inr * 100))  # Convert to paise

    try:
        refund = client.payment.refund(razorpay_payment_id, refund_data)
        logger.info(
            f"Refund initiated: refund_id={refund['id']}, "
            f"payment_id={razorpay_payment_id}, amount={refund.get('amount')}"
        )
        return refund

    except razorpay.errors.BadRequestError as e:
        logger.error(f"Razorpay refund BadRequest for {razorpay_payment_id}: {e}")
        raise HTTPException(status_code=400, detail=f"Refund failed: {str(e)}")
    except Exception as e:
        logger.error(f"Razorpay refund failed for {razorpay_payment_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Refund gateway error. Please try again or contact support.",
        )


def verify_webhook_signature(payload_body: bytes, received_signature: str) -> bool:
    """
    Verify Razorpay webhook signature.

    Razorpay signs the raw request body with WEBHOOK_SECRET using HMAC-SHA256.

    Args:
        payload_body:        Raw bytes of the webhook request body
        received_signature:  X-Razorpay-Signature header value

    Returns:
        True if valid, False otherwise.
    """
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET is not set — webhook verification disabled")
        return False

    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, received_signature)
