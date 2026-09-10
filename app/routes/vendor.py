from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.vendor_model import VendorProfile
from app.models.user_model import User
from app.schemas.vendor_schema import VendorApply, VendorResponse
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/vendor", tags=["Vendor"])


@router.post("/apply", response_model=VendorResponse)
def apply_vendor(
    data: VendorApply,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Admin ah vendor apply pannakoodathu
    if current_user.role == "admin":
        raise HTTPException(
            status_code=400, detail="Admin accounts cannot apply to become a vendor"
        )

    # Already vendor-a irundha, again apply pannakoodathu
    if current_user.role == "vendor":
        raise HTTPException(status_code=400, detail="You are already a vendor")

    # Already apply pannirundha check pannuvom
    existing = (
        db.query(VendorProfile).filter(VendorProfile.user_id == current_user.id).first()
    )

    if existing:
        if existing.status == "pending":
            raise HTTPException(
                status_code=400,
                detail="You already have a vendor application pending review",
            )
        if existing.status == "approved":
            # Ithu edge case - role vendor-a irukkanum already, but safety-ku
            raise HTTPException(status_code=400, detail="You are already a vendor")

        # status == "rejected" -> existing profile-a reset pannu, re-apply panna anumathikkuvom
        existing.shop_name = data.shop_name
        existing.business_address = data.business_address
        existing.gst_number = data.gst_number
        existing.status = "pending"
        existing.rejection_reason = None

        db.commit()
        db.refresh(existing)
        return existing

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
