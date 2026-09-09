from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class VendorApply(BaseModel):
    shop_name: str
    business_address: str
    gst_number: Optional[str] = None


class VendorResponse(BaseModel):
    id: int
    user_id: int
    shop_name: str
    business_address: str
    gst_number: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
