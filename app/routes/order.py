from typing import Optional
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.order_model import Order, OrderItem
from app.models.cart_model import CartItem
from app.models.product_model import Product
from app.models.user_model import User
from app.schemas.order_schema import CheckoutRequest, OrderResponse, OrderStatusUpdate
from app.utils.dependencies import get_current_user, role_required

router = APIRouter(prefix="/orders", tags=["Orders"])


# ---------------- CHECKOUT (Cart -> Order) ----------------
@router.post("/checkout", response_model=OrderResponse)
def checkout(
    data: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Cart items edukurom
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()

    if not cart_items:
        raise HTTPException(status_code=400, detail="Your cart is empty")

    # Ella products ku stock podhuma nu munnadiye check pannuvom
    for cart_item in cart_items:
        product = db.query(Product).filter(Product.id == cart_item.product_id).first()
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
                detail=f"Not enough stock for '{product.name}'. Available: {product.stock}, Requested: {cart_item.quantity}",
            )

    # Total amount calculate pannuvom
    total_amount = 0
    for cart_item in cart_items:
        product = db.query(Product).filter(Product.id == cart_item.product_id).first()
        total_amount += float(product.price) * cart_item.quantity

    # Order create pannuvom
    new_order = Order(
        user_id=current_user.id,
        total_amount=total_amount,
        status="pending",
        payment_status="unpaid",
        payment_method="cod",  # Razorpay integrate pannumbothu verify-payment route indha field ah "razorpay" nu update pannum
        shipping_name=data.shipping_name,
        shipping_phone=data.shipping_phone,
        shipping_address=data.shipping_address,
        shipping_city=data.shipping_city,
        shipping_pincode=data.shipping_pincode,
    )
    db.add(new_order)
    db.flush()  # new_order.id kidaikanum, commit pannama

    # Order items create pannuvom + stock reduce pannuvom
    for cart_item in cart_items:
        product = db.query(Product).filter(Product.id == cart_item.product_id).first()

        order_item = OrderItem(
            order_id=new_order.id,
            product_id=product.id,
            quantity=cart_item.quantity,
            price_at_purchase=product.price,
        )
        db.add(order_item)

        # Stock reduce pannuvom
        product.stock -= cart_item.quantity

    # Cart clear pannuvom
    db.query(CartItem).filter(CartItem.user_id == current_user.id).delete()

    db.commit()
    db.refresh(new_order)
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

    # Vendor tha oda product order mattum update pannanum
    if current_user.role == "vendor":
        vendor_has_product = any(
            item.product.vendor_id == current_user.id for item in order.items
        )
        if not vendor_has_product:
            raise HTTPException(
                status_code=403, detail="This order does not contain your products"
            )

    order.status = data.status
    db.commit()
    db.refresh(order)
    return order
