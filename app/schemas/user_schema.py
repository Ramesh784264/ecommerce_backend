from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


# Register request-la varum data
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


# Login request-la varum data
class UserLogin(BaseModel):
    email: EmailStr
    password: str


# Forgot password - email kudukanum
class ForgotPassword(BaseModel):
    email: EmailStr


# OTP verify panna
class OTPVerify(BaseModel):
    email: EmailStr
    otp_code: str


# Reset password - OTP verify aana pinnadi
class ResetPassword(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str


# Response-la client-ku thirupi anupura data (password kaatalama)
class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True
