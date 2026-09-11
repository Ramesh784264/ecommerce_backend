from typing import Optional
from datetime import date, datetime, time
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.order_model import Order, OrderItem
from app.models.cart_model import CartItem
from app.models.product_model import Product
from app.models.user_model import User
from app.models.coupon_model import Coupon, CouponUsage
from app.schemas.order_schema import CheckoutRequest, OrderResponse, OrderStatusUpdate
from app.utils.dependencies import get_current_user, role_required
from app.utils.email_utils import send_order_confirmation_email, send_order_status_email
from app.utils.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders"])


# ---------------- CHECKOUT (Cart -> Order) ----------------
@router.post("/checkout", response_model=OrderResponse)
def checkout(
    data: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch cart items
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Your cart is empty")

    # FIX: Fetch ALL products in a single IN query (eliminates N+1 problem)
    product_ids = [ci.product_id for ci in cart_items]
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    product_map = {p.id: p for p in products}

    # Validate stock for all items before touching anything
    for cart_item in cart_items:
        product = product_map.get(cart_item.product_id)
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product with id {cart_item.product_id} not found",
            )
        if not product.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"Product '{product.name}' is no longer available",
            )
        if product.stock < cart_item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough stock for '{product.name}'. "
                       f"Available: {product.stock}, Requested: {cart_item.quantity}",
            )

    # Calculate subtotal
    subtotal = sum(
        float(product_map[ci.product_id].price) * ci.quantity
        for ci in cart_items
    )

    # ── Coupon application ────────────────────────────────────────────────────
    discount_amount = 0.0
    applied_coupon = None

    if data.coupon_code:
        coupon = db.query(Coupon).filter(
            Coupon.code == data.coupon_code.upper()
        ).first()

        if not coupon:
            raise HTTPException(
                status_code=404,
                detail=f"Coupon code '{data.coupon_code}' not found",
            )

        # Validate eligibility (raises HTTPException on failure)
        from app.routes.coupon import _validate_coupon_eligibility, _calculate_discount
        _validate_coupon_eligibility(coupon, current_user.id, subtotal, db)
        discount_amount = _calculate_discount(coupon, subtotal)
        applied_coupon = coupon

    total_amount = round(subtotal - discount_amount, 2)

    # Create order
    new_order = Order(
        user_id=current_user.id,
        total_amount=total_amount,
        discount_amount=discount_amount,
        status="pending",
        payment_status="unpaid",
        payment_method="cod",
        shipping_name=data.shipping_name,
        shipping_phone=data.shipping_phone,
        shipping_address=data.shipping_address,
        shipping_city=data.shipping_city,
        shipping_pincode=data.shipping_pincode,
    )
    db.add(new_order)
    db.flush()  # Get new_order.id without committing

    # Create order items + deduct stock
    order_items_for_email = []
    # Track stock updates for WebSocket broadcast
    stock_updates = []
    for cart_item in cart_items:
        product = product_map[cart_item.product_id]
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=product.id,
            quantity=cart_item.quantity,
            price_at_purchase=product.price,
        )
        db.add(order_item)
        product.stock -= cart_item.quantity
        stock_updates.append((product.id, product.stock))
        order_items_for_email.append({
            "name": product.name,
            "quantity": cart_item.quantity,
            "price": float(product.price),
        })

    # Record coupon usage
    if applied_coupon:
        usage = CouponUsage(
            coupon_id=applied_coupon.id,
            user_id=current_user.id,
            order_id=new_order.id,
            discount_applied=discount_amount,
        )
        db.add(usage)
        applied_coupon.used_count += 1

    # Clear cart
    db.query(CartItem).filter(CartItem.user_id == current_user.id).delete()

    db.commit()
    db.refresh(new_order)

    # Send order confirmation email (fire-and-forget; failure won't raise)
    try:
        send_order_confirmation_email(
            to_email=current_user.email,
            name=current_user.name,
            order_id=new_order.id,
            total_amount=total_amount,
            items=order_items_for_email,
        )
    except Exception as e:
        logger.warning(f"Order confirmation email failed for order {new_order.id}: {e}")

    logger.info(
        f"Order #{new_order.id} created for user {current_user.id}, "
        f"total=₹{total_amount}, discount=₹{discount_amount}"
    )

    # ── Real-time WebSocket events ─────────────────────────────────────────────
    import asyncio

    async def _fire_order_events():
        # Notify the customer that their order was placed
        await ws_manager.send_to_user(current_user.id, {
            "type": "order_created",
            "data": {
                "order_id": new_order.id,
                "total_amount": total_amount,
                "status": "pending",
                "message": "Your order has been placed successfully!",
            }
        })
        # Notify all admin connections
        await ws_manager.broadcast_admins({
            "type": "new_order",
            "data": {
                "order_id": new_order.id,
                "user_id": current_user.id,
                "user_name": current_user.name,
                "total_amount": total_amount,
            }
        })
        # Broadcast real-time stock updates to all connected users and alert admins if low
        for p_id, remaining_stock in stock_updates:
            await ws_manager.broadcast({
                "type": "stock_update",
                "data": {
                    "product_id": p_id,
                    "stock": remaining_stock,
                }
            })
            if remaining_stock <= 5:
                await ws_manager.broadcast_admins({
                    "type": "low_stock_alert",
                    "data": {
                        "product_id": p_id,
                        "stock": remaining_stock,
                    }
                })

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_fire_order_events())
    except Exception as e:
        logger.warning(f"WS event failed for order {new_order.id}: {e}")

    return new_order



# ---------------- MY ORDERS (Customer) ----------------
@router.get("/my-orders", response_model=list[OrderResponse])
def get_my_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Order)
        .filter(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


# ---------------- GET SINGLE ORDER ----------------
@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Customer tha oda order mattum paakanum, Admin ellame paakalam
    if current_user.role == "customer" and order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view your own orders")

    return order


# ---------------- CANCEL ORDER (Customer) ----------------
@router.put("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="You can only cancel your own orders"
        )

    if order.status in ["shipped", "delivered", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order. Current status: {order.status}",
        )

    # Stock ah thirumba add pannuvom
    for item in order.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if product:
            product.stock += item.quantity

    order.status = "cancelled"

    # Order ku already payment aagi irundha, refund pending nu mark pannuvom
    # (Actual refund - Razorpay Refunds API vachi separate ah trigger pannanum)
    if order.payment_status == "paid":
        order.payment_status = "refund_pending"

    db.commit()
    return {"message": "Order cancelled successfully"}


# ---------------- ALL ORDERS (Admin only) ----------------
@router.get("/", response_model=list[OrderResponse])
def get_all_orders(
    status: Optional[str] = Query(None, description="Filter by order status"),
    payment_status: Optional[str] = Query(None, description="Filter by payment status"),
    from_date: Optional[date] = Query(
        None, description="Orders created on/after this date"
    ),
    to_date: Optional[date] = Query(
        None, description="Orders created on/before this date"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    query = db.query(Order)

    if status:
        query = query.filter(Order.status == status)
    if payment_status:
        query = query.filter(Order.payment_status == payment_status)
    if from_date:
        query = query.filter(Order.created_at >= datetime.combine(from_date, time.min))
    if to_date:
        query = query.filter(Order.created_at <= datetime.combine(to_date, time.max))

    return query.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()


# ---------------- UPDATE STATUS (Admin/Vendor) ----------------
@router.put("/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: int,
    data: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin", "vendor")),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Vendor can only update orders that contain their products
    if current_user.role == "vendor":
        vendor_has_product = any(
            item.product.vendor_id == current_user.id for item in order.items
        )
        if not vendor_has_product:
            raise HTTPException(
                status_code=403, detail="This order does not contain your products"
            )

    old_status = order.status
    order.status = data.status
    db.commit()
    db.refresh(order)

    # Send status update email + WebSocket event (fire-and-forget)
    if old_status != data.status:
        try:
            customer = db.query(User).filter(User.id == order.user_id).first()
            if customer:
                send_order_status_email(
                    to_email=customer.email,
                    name=customer.name,
                    order_id=order.id,
                    new_status=data.status,
                )
        except Exception as e:
            logger.warning(f"Status email failed for order {order.id}: {e}")

        # Real-time push to customer's WebSocket
        import asyncio

        async def _push_status():
            await ws_manager.send_to_user(order.user_id, {
                "type": "order_status_changed",
                "data": {
                    "order_id": order.id,
                    "old_status": old_status,
                    "new_status": data.status,
                    "message": f"Your order #{order.id} status changed to '{data.status}'",
                }
            })

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_push_status())
        except Exception as e:
            logger.warning(f"WS status push failed for order {order.id}: {e}")

    return order

