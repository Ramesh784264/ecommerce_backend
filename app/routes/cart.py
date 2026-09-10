from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.cart_model import CartItem
from app.models.product_model import Product
from app.models.user_model import User
from app.schemas.cart_schema import CartItemCreate, CartItemUpdate, CartItemResponse
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/cart", tags=["Cart"])


# ---------------- ADD TO CART ----------------
@router.post("/", response_model=CartItemResponse)
def add_to_cart(
    item: CartItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Product irukka nu check pannuvom
    product = db.query(Product).filter(Product.id == item.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Already cart-la iruka product-a nu check pannuvom
    existing_item = (
        db.query(CartItem)
        .filter(
            CartItem.user_id == current_user.id, CartItem.product_id == item.product_id
        )
        .first()
    )

    # Cart-la already irukkura quantity-yum, pudhusa add panra quantity-yum
    # sethu (combined) stock check pannuvom - illana stock mela order aagum
    current_qty_in_cart = existing_item.quantity if existing_item else 0
    total_requested_qty = current_qty_in_cart + item.quantity

    if product.stock < total_requested_qty:
        available_to_add = max(product.stock - current_qty_in_cart, 0)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Not enough stock available. In stock: {product.stock}, "
                f"already in your cart: {current_qty_in_cart}, "
                f"you can add up to {available_to_add} more."
            ),
        )

    if existing_item:
        # Already irukkuna quantity add pannuvom
        existing_item.quantity = total_requested_qty
        db.commit()
        db.refresh(existing_item)
        return existing_item

    # Pudhusa cart item create pannuvom
    new_item = CartItem(
        user_id=current_user.id, product_id=item.product_id, quantity=item.quantity
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


# ---------------- VIEW CART ----------------
@router.get("/", response_model=list[CartItemResponse])
def view_cart(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return db.query(CartItem).filter(CartItem.user_id == current_user.id).all()


# ---------------- UPDATE QUANTITY ----------------
@router.put("/{cart_item_id}", response_model=CartItemResponse)
def update_cart_item(
    cart_item_id: int,
    data: CartItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = (
        db.query(CartItem)
        .filter(CartItem.id == cart_item_id, CartItem.user_id == current_user.id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")

    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")

    # Product current stock-ku etthiraga update panra quantity check pannuvom
    product = db.query(Product).filter(Product.id == item.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if product.stock < data.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough stock available. In stock: {product.stock}",
        )

    item.quantity = data.quantity
    db.commit()
    db.refresh(item)
    return item


# ---------------- REMOVE FROM CART ----------------
@router.delete("/{cart_item_id}")
def remove_from_cart(
    cart_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = (
        db.query(CartItem)
        .filter(CartItem.id == cart_item_id, CartItem.user_id == current_user.id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")

    db.delete(item)
    db.commit()
    return {"message": "Item removed from cart"}


# ---------------- CLEAR CART ----------------
@router.delete("/")
def clear_cart(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    db.query(CartItem).filter(CartItem.user_id == current_user.id).delete()
    db.commit()
    return {"message": "Cart cleared"}
