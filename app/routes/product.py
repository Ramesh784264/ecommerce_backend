from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.product_model import Product
from app.schemas.product_schema import ProductCreate, ProductUpdate, ProductResponse
from app.utils.dependencies import get_current_user, role_required

router = APIRouter(prefix="/products", tags=["Products"])


# ---------------- CREATE (Admin/Vendor only) ----------------
@router.post("/", response_model=ProductResponse)
def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin", "vendor")),
):
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


# ---------------- GET ALL (Everyone, with search/filter) ----------------
@router.get("/", response_model=list[ProductResponse])
def get_products(
    db: Session = Depends(get_db),
    search: str = None,
    category_id: int = None,
    min_price: float = None,
    max_price: float = None,
):
    query = db.query(Product)

    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    return query.all()


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

    update_data = product_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)
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

    db.delete(product)
    db.commit()
    return {"message": "Product deleted successfully"}
