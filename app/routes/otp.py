"""
OTP Verification & Forgot Password Routes

Endpoints:
  POST /auth/send-otp              → Send OTP to email (for new user verification)
  POST /auth/verify-email          → Verify email OTP → mark user as verified
  POST /auth/forgot-password       → Send OTP to registered email
  POST /auth/reset-password        → Verify OTP + set new password
  POST /auth/resend-otp            → Resend OTP (rate-limited in production)

Design decisions:
  - OTP is 6 digits, expires in 10 minutes
  - Same endpoint flow for email-verify and password-reset (same OTP column on user)
  - Email sending is fire-and-forget (failure doesn't block the response)
  - Expiry and invalid OTP use the same error message to prevent user enumeration
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user_model import User
from app.schemas.user_schema import (
    ForgotPassword,
    OTPVerify,
    ResetPassword,
    UserResponse,
)
from app.utils.dependencies import get_current_user
from app.utils.email_utils import send_otp_email
from app.utils.otp import clear_otp, save_otp, verify_otp
from app.utils.password import hash_password, verify_password

logger = logging.getLogger(__name__)

# This router is mounted on auth.py's router via include_router, or directly in main.py
# We keep it separate for clarity
router = APIRouter(prefix="/auth", tags=["OTP & Password"])


# ──────────────────────────────────────────────
# SEND OTP — Email Verification (after register)
# ──────────────────────────────────────────────

@router.post("/send-otp")
def send_verification_otp(
    data: ForgotPassword,  # Reuses the {email} schema
    db: Session = Depends(get_db),
):
    """
    Send a 6-digit OTP to the user's email for account verification.
    Call this after /auth/register to verify the new account.

    Security: Returns the same success message whether or not email exists,
    to prevent user enumeration attacks.
    """
    user = db.query(User).filter(User.email == data.email).first()

    if user and not user.is_verified:
        otp = save_otp(user, db)
        send_otp_email(
            to_email=user.email,
            name=user.name,
            otp=otp,
            purpose="verification",
        )
        logger.info(f"Verification OTP sent to {data.email}")

    # Always return same message (anti-enumeration)
    return {
        "message": "If this email is registered and unverified, you will receive an OTP shortly."
    }


# ──────────────────────────────────────────────
# VERIFY EMAIL OTP
# ──────────────────────────────────────────────

@router.post("/verify-email", response_model=UserResponse)
def verify_email(data: OTPVerify, db: Session = Depends(get_db)):
    """
    Verify the OTP sent to the user's email.
    On success: user.is_verified = True, OTP is cleared.
    """
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid OTP or OTP has expired")

    if user.is_verified:
        raise HTTPException(status_code=400, detail="Email is already verified")

    valid, reason = verify_otp(user, data.otp_code)
    if not valid:
        # Use generic message for both expired and invalid to prevent brute-force hints
        raise HTTPException(status_code=400, detail="Invalid OTP or OTP has expired")

    user.is_verified = True
    clear_otp(user, db)

    logger.info(f"Email verified for user_id={user.id}")
    return user


# ──────────────────────────────────────────────
# FORGOT PASSWORD — Send OTP
# ──────────────────────────────────────────────

@router.post("/forgot-password")
def forgot_password(data: ForgotPassword, db: Session = Depends(get_db)):
    """
    Trigger a password-reset OTP email.

    Security: Always returns 200 so attackers can't enumerate registered emails.
    """
    user = db.query(User).filter(User.email == data.email).first()

    if user and user.is_active:
        otp = save_otp(user, db)
        send_otp_email(
            to_email=user.email,
            name=user.name,
            otp=otp,
            purpose="password_reset",
        )
        logger.info(f"Password reset OTP sent for user_id={user.id}")

    return {
        "message": "If this email is registered, you will receive a password reset OTP shortly."
    }


# ──────────────────────────────────────────────
# RESET PASSWORD — Verify OTP + Set New Password
# ──────────────────────────────────────────────

@router.post("/reset-password")
def reset_password(data: ResetPassword, db: Session = Depends(get_db)):
    """
    Set a new password after verifying the OTP.
    Requires: email + otp_code + new_password
    """
    # Validate new password strength
    if len(data.new_password) < 8:
        raise HTTPException(
            status_code=400, detail="New password must be at least 8 characters"
        )

    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid OTP or OTP has expired")

    valid, reason = verify_otp(user, data.otp_code)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid OTP or OTP has expired")

    # Set new password
    user.password_hash = hash_password(data.new_password)
    clear_otp(user, db)

    logger.info(f"Password reset successful for user_id={user.id}")
    return {"message": "Password reset successful. You can now log in with your new password."}


# ──────────────────────────────────────────────
# CHANGE PASSWORD (Logged-in user)
# ──────────────────────────────────────────────

from pydantic import BaseModel


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Authenticated user changes their own password.
    Requires the current password for verification (prevents session hijacking).
    """
    if len(data.new_password) < 8:
        raise HTTPException(
            status_code=400, detail="New password must be at least 8 characters"
        )

    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if data.current_password == data.new_password:
        raise HTTPException(
            status_code=400, detail="New password must be different from current password"
        )

    current_user.password_hash = hash_password(data.new_password)
    db.commit()

    logger.info(f"Password changed for user_id={current_user.id}")
    return {"message": "Password changed successfully"}


# ──────────────────────────────────────────────
# RESEND OTP
# ──────────────────────────────────────────────

@router.post("/resend-otp")
def resend_otp(data: ForgotPassword, db: Session = Depends(get_db)):
    """
    Resend an OTP for either verification or password reset.
    Generates a fresh OTP (invalidating any previous one).

    TODO (production): Add rate limiting — max 3 OTP requests per 15 minutes per email.
    """
    user = db.query(User).filter(User.email == data.email).first()

    if user:
        otp = save_otp(user, db)
        purpose = "password_reset" if user.is_verified else "verification"
        send_otp_email(
            to_email=user.email,
            name=user.name,
            otp=otp,
            purpose=purpose,
        )
        logger.info(f"OTP resent for user_id={user.id}")

    return {"message": "A new OTP has been sent to your email if it is registered."}
