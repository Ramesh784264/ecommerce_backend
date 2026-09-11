from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.wishlist_model import WishlistItem
from app.models.cart_model import CartItem
from app.models.product_model import Product
from app.models.user_model import User
from app.schemas.wishlist_schema import WishlistItemCreate, WishlistItemResponse
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/wishlist", tags=["Wishlist"])


@router.post("/", response_model=WishlistItemResponse)
def add_to_wishlist(
    item: WishlistItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(Product.id == item.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = (
        db.query(WishlistItem)
        .filter(
            WishlistItem.user_id == current_user.id,
            WishlistItem.product_id == item.product_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Product already in wishlist")

    new_item = WishlistItem(user_id=current_user.id, product_id=item.product_id)
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


@router.get("/", response_model=list[WishlistItemResponse])
def view_wishlist(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return db.query(WishlistItem).filter(WishlistItem.user_id == current_user.id).all()


@router.delete("/{wishlist_item_id}")
def remove_from_wishlist(
    wishlist_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = (
        db.query(WishlistItem)
        .filter(
            WishlistItem.id == wishlist_item_id, WishlistItem.user_id == current_user.id
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Wishlist item not found")

    db.delete(item)
    db.commit()
    return {"message": "Item removed from wishlist"}


@router.post("/{wishlist_item_id}/move-to-cart")
def move_to_cart(
    wishlist_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wishlist_item = (
        db.query(WishlistItem)
        .filter(
            WishlistItem.id == wishlist_item_id, WishlistItem.user_id == current_user.id
        )
        .first()
    )
    if not wishlist_item:
        raise HTTPException(status_code=404, detail="Wishlist item not found")

    # Validate stock before moving to cart
    product = db.query(Product).filter(Product.id == wishlist_item.product_id).first()
    if not product or not product.is_active:
        raise HTTPException(status_code=400, detail="Product is no longer available")
    if product.stock < 1:
        raise HTTPException(status_code=400, detail=f"'{product.name}' is out of stock")

    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.user_id == current_user.id,
            CartItem.product_id == wishlist_item.product_id,
        )
        .first()
    )

    if cart_item:
        if product.stock < cart_item.quantity + 1:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough stock. Only {product.stock} left and you already have {cart_item.quantity} in cart.",
            )
        cart_item.quantity += 1
    else:
        cart_item = CartItem(
            user_id=current_user.id, product_id=wishlist_item.product_id, quantity=1
        )
        db.add(cart_item)

    db.delete(wishlist_item)
    db.commit()
    return {"message": "Item moved to cart"}
