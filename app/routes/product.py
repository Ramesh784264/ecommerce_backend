import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.product_model import Product
from app.models.category_model import Category
from app.schemas.product_schema import ProductCreate, ProductUpdate, ProductResponse
from app.utils.dependencies import get_current_user, role_required
from app.utils.ws_manager import ws_manager

router = APIRouter(prefix="/products", tags=["Products"])


# ---------------- CREATE (Admin/Vendor only) ----------------
@router.post("/", response_model=ProductResponse)
def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin", "vendor")),
):
    # Category exist pannuthaa nu check pannuvom
    category = db.query(Category).filter(Category.id == product.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Same vendor, same product name, same category already irukka nu check pannuvom
    existing = (
        db.query(Product)
        .filter(
            Product.name == product.name,
            Product.vendor_id == current_user.id,
            Product.category_id == product.category_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"You already have a product named '{product.name}' in this category. Please use a different name or edit the existing product.",
        )

    new_product = Product(
        name=product.name,
        description=product.description,
        price=product.price,
        stock=product.stock,
        image_url=product.image_url,
        category_id=product.category_id,
        vendor_id=current_user.id,
    )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product


# ---------------- COUNT (Everyone) — {product_id} route ku MUNNADI irukanum ----------------
@router.get("/count")
def get_products_count(
    db: Session = Depends(get_db),
    search: str = None,
    category_id: int = None,
):
    query = db.query(Product).filter(Product.is_active == True)

    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter(Product.category_id == category_id)

    total = query.count()
    return {"total_products": total}


# ---------------- GET ALL (Everyone, with search/filter/pagination) ----------------
@router.get("/", response_model=list[ProductResponse])
def get_products(
    db: Session = Depends(get_db),
    search: str = None,
    category_id: int = None,
    min_price: float = None,
    max_price: float = None,
    skip: int = 0,
    limit: int = 20,
):
    query = db.query(Product).filter(Product.is_active == True)

    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    # Return empty list (not 404) when no products match — correct REST semantics
    return query.offset(skip).limit(limit).all()


# ---------------- GET ONE (Everyone) ----------------
@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# ---------------- UPDATE (Owner vendor / Admin only) ----------------
@router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    product_data: ProductUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin", "vendor")),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Vendor tha oda product mattum edit pannanum, admin ellame edit pannlaam
    if current_user.role == "vendor" and product.vendor_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="You can only edit your own products"
        )

    update_data = product_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)

    # ── Real-time WebSocket stock update ──────────────────────
    if "stock" in update_data:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(ws_manager.broadcast({
                    "type": "stock_update",
                    "data": {
                        "product_id": product.id,
                        "stock": product.stock,
                    }
                }))
                if product.stock <= 5:
                    asyncio.ensure_future(ws_manager.broadcast_admins({
                        "type": "low_stock_alert",
                        "data": {
                            "product_id": product.id,
                            "product_name": product.name,
                            "stock": product.stock,
                        }
                    }))
        except Exception:
            pass

    return product


# ---------------- DELETE (Owner vendor / Admin only) ----------------
@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin", "vendor")),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if current_user.role == "vendor" and product.vendor_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="You can only delete your own products"
        )

    # Soft-delete: set is_active = False instead of hard deletion.
    # This preserves referential integrity with existing order_items.
    product.is_active = False
    db.commit()
    return {"message": "Product deleted successfully"}
