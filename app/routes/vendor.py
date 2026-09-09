from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.vendor_model import VendorProfile
from app.models.user_model import User
from app.schemas.vendor_schema import VendorApply, VendorResponse
from app.utils.dependencies import get_current_user, role_required

router = APIRouter(prefix="/vendor", tags=["Vendor"])


# ---------------- APPLY (Logged-in customer) ----------------
@router.post("/apply", response_model=VendorResponse)
def apply_vendor(
    data: VendorApply,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Already vendor-a irundhaa illa already apply pannirundhaa check pannuvom
    existing = (
        db.query(VendorProfile).filter(VendorProfile.user_id == current_user.id).first()
    )
    if existing:
        raise HTTPException(
            status_code=400, detail="You have already applied or are a vendor"
        )

    new_vendor = VendorProfile(
        user_id=current_user.id,
        shop_name=data.shop_name,
        business_address=data.business_address,
        gst_number=data.gst_number,
        status="pending",
    )
    db.add(new_vendor)
    db.commit()
    db.refresh(new_vendor)
    return new_vendor


# ---------------- MY STATUS (Logged-in user check own application) ----------------
@router.get("/my-status", response_model=VendorResponse)
def my_vendor_status(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    vendor = (
        db.query(VendorProfile).filter(VendorProfile.user_id == current_user.id).first()
    )
    if not vendor:
        raise HTTPException(status_code=404, detail="No vendor application found")
    return vendor
