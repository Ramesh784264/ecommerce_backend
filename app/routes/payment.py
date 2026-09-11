"""
Payment Routes — Razorpay Integration

Endpoints:
  POST  /payments/create-order     → Create Razorpay order for an existing DB order
  POST  /payments/verify           → Verify signature after frontend payment
  POST  /payments/webhook          → Razorpay async webhook handler
  POST  /payments/{order_id}/refund → Admin: trigger refund
  GET   /payments/{order_id}/status → Customer/Admin: check payment status
  GET   /payments/{order_id}/logs   → Admin: audit log of all payment events
"""

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.order_model import Order
from app.models.payment_model import PaymentLog
from app.models.user_model import User
from app.schemas.payment_schema import (
    PaymentLogResponse,
    PaymentStatusResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
    RazorpayOrderCreate,
    RazorpayOrderResponse,
    RefundRequest,
    RefundResponse,
)
from app.utils.dependencies import get_current_user, role_required
from app.utils.razorpay_utils import (
    create_razorpay_order,
    trigger_refund,
    verify_payment_signature,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])


# ──────────────────────────────────────────────────────────────────────────────
# HELPER — fetch order and enforce ownership
# ──────────────────────────────────────────────────────────────────────────────

def _get_order_for_user(order_id: int, current_user: User, db: Session) -> Order:
    """
    Fetch an order, raising 404 if it doesn't exist.
    Raises 403 if the current customer tries to access another user's order.
    Admins can access any order.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if current_user.role == "customer" and order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own orders",
        )
    return order


def _log_payment_event(
    db: Session,
    *,
    order_id: int,
    event_type: str,
    razorpay_order_id: str | None = None,
    razorpay_payment_id: str | None = None,
    razorpay_refund_id: str | None = None,
    amount_inr: float | None = None,
    raw_response: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Insert a row into payment_logs for every Razorpay interaction."""
    log = PaymentLog(
        order_id=order_id,
        event_type=event_type,
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_refund_id=razorpay_refund_id,
        amount=amount_inr,
        raw_response=json.dumps(raw_response) if raw_response else None,
        error_message=error_message,
    )
    db.add(log)
    db.flush()  # Don't commit here — caller owns the transaction


# ──────────────────────────────────────────────────────────────────────────────
# 1. CREATE RAZORPAY ORDER
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/create-order", response_model=RazorpayOrderResponse)
def create_payment_order(
    data: RazorpayOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Step 1 of the payment flow.

    Call this after `/orders/checkout` succeeds.
    Returns the Razorpay `order_id`, `amount`, and `key_id` needed to open
    the Razorpay checkout popup in the frontend.

    Flow:
      1. Verify order belongs to current user and is in 'pending' + 'unpaid' state
      2. Create Razorpay order via API
      3. Store razorpay_order_id on our Order row
      4. Return details for frontend checkout
    """
    order = _get_order_for_user(data.order_id, current_user, db)

    # Guard: don't create a Razorpay order if already paid
    if order.payment_status == "paid":
        raise HTTPException(status_code=400, detail="This order is already paid")

    if order.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot pay for a cancelled order")

    # Create Razorpay order (amount in INR, receipt = our internal order ID)
    razorpay_order = create_razorpay_order(
        amount_inr=float(order.total_amount),
        receipt=f"order_{order.id}",
    )

    # Persist Razorpay order ID to our DB row
    order.razorpay_order_id = razorpay_order["id"]
    order.payment_method = "razorpay"

    # Audit log
    _log_payment_event(
        db,
        order_id=order.id,
        event_type="created",
        razorpay_order_id=razorpay_order["id"],
        amount_inr=float(order.total_amount),
        raw_response=razorpay_order,
    )

    db.commit()

    logger.info(f"Razorpay order created for order_id={order.id}: {razorpay_order['id']}")

    return RazorpayOrderResponse(
        razorpay_order_id=razorpay_order["id"],
        amount=razorpay_order["amount"],   # Amount in paise
        currency=razorpay_order["currency"],
        key_id=os.getenv("RAZORPAY_KEY_ID", ""),
        order_db_id=order.id,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2. VERIFY PAYMENT SIGNATURE
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/verify", response_model=PaymentVerifyResponse)
def verify_payment(
    data: PaymentVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Step 2 of the payment flow.

    After the Razorpay popup completes, the frontend sends the 3 Razorpay
    identifiers here. We verify the HMAC-SHA256 signature to confirm the
    payment is authentic (not tampered with).

    On success:
      - Order payment_status → 'paid'
      - Order status → 'confirmed'
      - razorpay_payment_id and razorpay_signature stored on order

    Security: Signature verification uses HMAC, so even if an attacker knows
    the order ID and payment ID, they cannot forge a valid signature without
    the key_secret.
    """
    # Find order by Razorpay order ID
    order = (
        db.query(Order)
        .filter(Order.razorpay_order_id == data.razorpay_order_id)
        .first()
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail="No order found for this Razorpay order ID",
        )

    # Ensure the order belongs to the current user
    if current_user.role == "customer" and order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # Idempotency: already verified
    if order.payment_status == "paid":
        return PaymentVerifyResponse(
            success=True,
            message="Payment already verified",
            order_id=order.id,
            payment_status=order.payment_status,
        )

    # ── CRITICAL: Verify Razorpay signature ──
    is_valid = verify_payment_signature(
        razorpay_order_id=data.razorpay_order_id,
        razorpay_payment_id=data.razorpay_payment_id,
        razorpay_signature=data.razorpay_signature,
    )

    if not is_valid:
        # Log the failure for security audit
        _log_payment_event(
            db,
            order_id=order.id,
            event_type="failed",
            razorpay_order_id=data.razorpay_order_id,
            razorpay_payment_id=data.razorpay_payment_id,
            error_message="Signature verification failed",
        )
        db.commit()

        logger.warning(
            f"Payment signature verification FAILED for order_id={order.id}, "
            f"razorpay_payment_id={data.razorpay_payment_id}"
        )
        raise HTTPException(
            status_code=400,
            detail="Payment verification failed. Signature mismatch.",
        )

    # ── Signature valid — mark order as paid ──
    order.payment_status = "paid"
    order.status = "confirmed"
    order.razorpay_payment_id = data.razorpay_payment_id
    order.razorpay_signature = data.razorpay_signature

    _log_payment_event(
        db,
        order_id=order.id,
        event_type="captured",
        razorpay_order_id=data.razorpay_order_id,
        razorpay_payment_id=data.razorpay_payment_id,
        amount_inr=float(order.total_amount),
    )

    db.commit()

    logger.info(
        f"Payment verified & captured for order_id={order.id}, "
        f"payment_id={data.razorpay_payment_id}"
    )

    return PaymentVerifyResponse(
        success=True,
        message="Payment successful! Your order is confirmed.",
        order_id=order.id,
        payment_status=order.payment_status,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 3. RAZORPAY WEBHOOK (async payment events)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/webhook", status_code=200)
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Razorpay sends webhook events for:
      - payment.captured
      - payment.failed
      - refund.created
      - order.paid

    This handler is a safety net: if the user closes the browser before
    /verify is called, the webhook still marks the order as paid.

    Security: Webhook signature is verified using RAZORPAY_WEBHOOK_SECRET.

    Setup in Razorpay Dashboard:
      Settings → Webhooks → Add New Webhook URL → https://yourdomain.com/payments/webhook
    """
    payload_bytes = await request.body()
    received_signature = request.headers.get("X-Razorpay-Signature", "")

    # Verify webhook authenticity
    if not verify_webhook_signature(payload_bytes, received_signature):
        logger.warning("Webhook received with invalid signature — rejected")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        logger.error("Webhook payload is not valid JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})

    razorpay_order_id = entity.get("order_id")
    razorpay_payment_id = entity.get("id")
    amount_paise = entity.get("amount", 0)
    amount_inr = amount_paise / 100

    logger.info(f"Webhook event received: {event} for razorpay_order_id={razorpay_order_id}")

    order = (
        db.query(Order).filter(Order.razorpay_order_id == razorpay_order_id).first()
        if razorpay_order_id
        else None
    )

    if not order:
        # Unknown order — log and return 200 so Razorpay doesn't retry endlessly
        logger.warning(f"Webhook: no order found for razorpay_order_id={razorpay_order_id}")
        return {"status": "ignored", "reason": "order not found"}

    # ── Handle different event types ──
    if event == "payment.captured":
        if order.payment_status != "paid":
            order.payment_status = "paid"
            order.status = "confirmed"
            if razorpay_payment_id:
                order.razorpay_payment_id = razorpay_payment_id

            _log_payment_event(
                db,
                order_id=order.id,
                event_type="webhook_captured",
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                amount_inr=amount_inr,
                raw_response=payload,
            )
            db.commit()
            logger.info(f"Webhook: order_id={order.id} marked as paid via webhook")

    elif event == "payment.failed":
        error_desc = entity.get("error_description", "Payment failed")

        _log_payment_event(
            db,
            order_id=order.id,
            event_type="webhook_failed",
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            amount_inr=amount_inr,
            raw_response=payload,
            error_message=error_desc,
        )
        db.commit()
        logger.info(f"Webhook: payment failed for order_id={order.id}: {error_desc}")

    elif event == "refund.created":
        refund_entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
        refund_id = refund_entity.get("id")

        _log_payment_event(
            db,
            order_id=order.id,
            event_type="webhook_refund_created",
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_refund_id=refund_id,
            amount_inr=refund_entity.get("amount", 0) / 100,
            raw_response=payload,
        )
        db.commit()

    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# 4. TRIGGER REFUND (Admin only)
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/{order_id}/refund", response_model=RefundResponse)
def refund_payment(
    order_id: int,
    data: RefundRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Admin triggers a refund for a paid order.

    - Full refund: don't send `amount` in request body
    - Partial refund: send `amount` in INR (e.g., 199.00)

    After refund is initiated:
      - order.payment_status → 'refund_pending'
      - Razorpay will send a webhook when refund is processed

    Note: Refunds take 5-7 business days to reach the customer's account.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status != "paid":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot refund — current payment status is '{order.payment_status}'",
        )

    if not order.razorpay_payment_id:
        raise HTTPException(
            status_code=400,
            detail="No Razorpay payment ID found for this order. Cannot process refund.",
        )

    # Validate partial refund amount
    refund_amount = data.amount
    if refund_amount and refund_amount > float(order.total_amount):
        raise HTTPException(
            status_code=400,
            detail=f"Refund amount ₹{refund_amount} exceeds order total ₹{order.total_amount}",
        )

    # Call Razorpay refund API
    refund_data = trigger_refund(
        razorpay_payment_id=order.razorpay_payment_id,
        amount_inr=refund_amount,
    )

    refund_id = refund_data.get("id")
    actual_refund_amount_inr = refund_data.get("amount", 0) / 100

    # Update order payment status
    order.payment_status = "refund_pending"

    _log_payment_event(
        db,
        order_id=order.id,
        event_type="refund_initiated",
        razorpay_order_id=order.razorpay_order_id,
        razorpay_payment_id=order.razorpay_payment_id,
        razorpay_refund_id=refund_id,
        amount_inr=actual_refund_amount_inr,
        raw_response=refund_data,
    )

    db.commit()

    logger.info(
        f"Refund initiated for order_id={order.id}, "
        f"refund_id={refund_id}, amount=₹{actual_refund_amount_inr}"
    )

    return RefundResponse(
        success=True,
        message=f"Refund of ₹{actual_refund_amount_inr:.2f} initiated successfully. "
                f"It will reach the customer in 5-7 business days.",
        refund_id=refund_id,
        refund_amount=actual_refund_amount_inr,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 5. GET PAYMENT STATUS
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{order_id}/status", response_model=PaymentStatusResponse)
def get_payment_status(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the payment status of an order.
    Customers can only see their own orders; admins can see all.
    """
    order = _get_order_for_user(order_id, current_user, db)

    return PaymentStatusResponse(
        order_id=order.id,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        razorpay_order_id=order.razorpay_order_id,
        razorpay_payment_id=order.razorpay_payment_id,
        total_amount=float(order.total_amount),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 6. PAYMENT AUDIT LOGS (Admin only)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{order_id}/logs", response_model=list[PaymentLogResponse])
def get_payment_logs(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    """
    Admin endpoint to view the full payment audit trail for an order.
    Useful for debugging payment issues and customer disputes.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    logs = (
        db.query(PaymentLog)
        .filter(PaymentLog.order_id == order_id)
        .order_by(PaymentLog.created_at.asc())
        .all()
    )
    return logs
