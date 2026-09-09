from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime


# Register request-la varum data
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty")
        if len(value) > 20:
            raise ValueError("Name must be at most 20 characters")
        if not value.replace(" ", "").isalpha():
            raise ValueError("Name must contain letters only")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):

        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(value) > 16:
            raise ValueError("Password must be at most 16 characters")
        return value


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
