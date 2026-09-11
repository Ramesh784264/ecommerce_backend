from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.vendor_model import VendorProfile
from app.models.user_model import User
from app.schemas.vendor_schema import VendorResponse
from app.utils.dependencies import role_required
from app.schemas.user_schema import UserResponse
from app.utils.email_utils import send_vendor_decision_email
import logging

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/admin", tags=["Admin"])


# get all users (paginated)
@router.get("/users", response_model=list[UserResponse])
def get_all_users(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin")),
):
    return db.query(User).offset(skip).limit(limit).all()


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(role_required("admin")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=400, detail="You cannot delete your own account"
        )

    db.delete(user)
    db.commit()
    return {"message": f"User {user.id} deleted successfully"}


# ---------------- VIEW PENDING VENDOR REQUESTS (Admin only) ----------------
@router.get("/vendor-requests", response_model=list[VendorResponse])
def get_vendor_requests(
    db: Session = Depends(get_db), current_user=Depends(role_required("admin"))
):
    return db.query(VendorProfile).filter(VendorProfile.status == "pending").all()


# ---------------- APPROVE VENDOR (Admin only) ----------------
@router.put("/approve-vendor/{vendor_id}")
def approve_vendor(
    vendor_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin")),
):
    vendor = db.query(VendorProfile).filter(VendorProfile.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor application not found")

    if vendor.status == "approved":
        raise HTTPException(status_code=400, detail="Vendor is already approved")

    user = db.query(User).filter(User.id == vendor.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Associated user account not found")

    vendor.status = "approved"
    user.role = "vendor"

    db.commit()

    # Notify vendor by email
    try:
        send_vendor_decision_email(
            to_email=user.email, name=user.name,
            shop_name=vendor.shop_name, approved=True
        )
    except Exception as e:
        logger.warning(f"Vendor approval email failed: {e}")

    return {"message": f"Vendor '{vendor.shop_name}' approved successfully"}


# ---------------- REJECT VENDOR (Admin only) ----------------
class VendorRejectBody(BaseModel):
    rejection_reason: str = ""


@router.put("/reject-vendor/{vendor_id}")
def reject_vendor(
    vendor_id: int,
    body: VendorRejectBody = VendorRejectBody(),
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin")),
):
    vendor = db.query(VendorProfile).filter(VendorProfile.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor application not found")

    vendor.status = "rejected"
    vendor.rejection_reason = body.rejection_reason or "Application did not meet requirements."
    db.commit()

    # Notify vendor by email
    try:
        user = db.query(User).filter(User.id == vendor.user_id).first()
        if user:
            send_vendor_decision_email(
                to_email=user.email, name=user.name,
                shop_name=vendor.shop_name, approved=False,
                reason=vendor.rejection_reason,
            )
    except Exception as e:
        logger.warning(f"Vendor rejection email failed: {e}")

    return {"message": "Vendor application rejected"}
