from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user_model import User
from app.schemas.user_schema import UserCreate, UserLogin, UserResponse
from app.utils.password import hash_password, verify_password
from app.utils.jwt_handler import create_access_token
from app.utils.dependencies import get_current_user, role_required

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------- REGISTER ----------------
@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    # Email already irukka nu check pannuvom
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Password hash pannuvom
    hashed_pw = hash_password(user.password)

    # Pudhu user create pannuvom
    new_user = User(name=user.name, email=user.email, password_hash=hashed_pw)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


# ---------------- LOGIN ----------------
@router.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    # Email vachi user find pannuvom
    db_user = db.query(User).filter(User.email == user.email).first()
    if not db_user:
        raise HTTPException(status_code=400, detail="Invalid email or password")

    # Check account is active (not banned/soft-deleted)
    if not db_user.is_active:
        raise HTTPException(status_code=403, detail="Your account has been deactivated")

    # Password correct-a nu check pannuvom
    if not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid email or password")

    # JWT token create pannuvom
    access_token = create_access_token(
        data={"user_id": db_user.id, "email": db_user.email, "role": db_user.role}
    )

    return {"access_token": access_token, "token_type": "bearer", "role": db_user.role}


# Login pannin yaaru nu check panna
@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# Admin mattum access panna example route
@router.get("/admin-only")
def admin_dashboard(current_user: User = Depends(role_required("admin"))):
    return {"message": f"Welcome Admin {current_user.name}"}
