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

    # Stock check pannuvom
    if product.stock < item.quantity:
        raise HTTPException(status_code=400, detail="Not enough stock available")

    # Already cart-la iruka product-a nu check pannuvom
    existing_item = (
        db.query(CartItem)
        .filter(
            CartItem.user_id == current_user.id, CartItem.product_id == item.product_id
        )
        .first()
    )

    if existing_item:
        # Already irukkuna quantity add pannuvom
        existing_item.quantity += item.quantity
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
