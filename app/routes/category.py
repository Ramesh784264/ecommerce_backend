from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.category_model import Category
from app.schemas.category_schema import CategoryCreate, CategoryUpdate, CategoryResponse
from app.utils.dependencies import role_required

router = APIRouter(prefix="/categories", tags=["Categories"])


# ---------------- CREATE (Admin only) ----------------
@router.post("/", response_model=CategoryResponse)
def create_category(
    category: CategoryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin")),
):
    existing = db.query(Category).filter(Category.name == category.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")

    new_category = Category(name=category.name, description=category.description)
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return new_category


# ---------------- GET ALL (Everyone) ----------------
@router.get("/", response_model=list[CategoryResponse])
def get_categories(db: Session = Depends(get_db)):
    return db.query(Category).all()


# ---------------- UPDATE (Admin only) ----------------
@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: int,
    data: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin")),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(
            status_code=404, detail=f"Category not found with this id {category_id}"
        )

    # Vera category same name use pannuthaa nu check pannuvom (name update pannina)
    if data.name and data.name != category.name:
        name_exists = db.query(Category).filter(Category.name == data.name).first()
        if name_exists:
            raise HTTPException(
                status_code=400, detail="Category with this name already exists"
            )

    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(category, key, value)

    db.commit()
    db.refresh(category)
    return category


# ---------------- DELETE (Admin only) ----------------
@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin")),
):
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(
            status_code=404, detail=f"Category not found with this id {category_id}"
        )

    db.delete(category)
    db.commit()
    return {"message": f"Category {category.id} deleted successfully"}
