from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.vendor_model import VendorProfile
from app.models.user_model import User
from app.schemas.vendor_schema import VendorResponse
from app.utils.dependencies import role_required

router = APIRouter(prefix="/admin", tags=["Admin"])


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
    return {"message": f"Vendor '{vendor.shop_name}' approved successfully"}


# ---------------- REJECT VENDOR (Admin only) ----------------
@router.put("/reject-vendor/{vendor_id}")
def reject_vendor(
    vendor_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(role_required("admin")),
):
    vendor = db.query(VendorProfile).filter(VendorProfile.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor application not found")

    vendor.status = "rejected"
    db.commit()
    return {"message": "Vendor application rejected"}
