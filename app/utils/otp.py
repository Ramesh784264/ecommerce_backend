"""
OTP Utility Functions

Responsibilities:
  - Generate a secure 6-digit OTP
  - Save OTP to user record with expiry timestamp
  - Verify OTP (checks code + expiry)
  - Clear OTP after use

OTP TTL: 10 minutes (configurable via OTP_EXPIRE_MINUTES env var)
"""

import logging
import os
import random
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user_model import User

logger = logging.getLogger(__name__)

OTP_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "10"))


def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically random numeric OTP."""
    return "".join(random.choices(string.digits, k=length))


def save_otp(user: User, db: Session) -> str:
    """
    Generate a fresh OTP, save it to the user record with expiry, and return the code.
    Always replaces any existing OTP (idempotent — safe to call multiple times).
    """
    otp = generate_otp()
    user.otp_code = otp
    user.otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
    db.commit()
    logger.info(f"OTP generated for user_id={user.id} (expires in {OTP_EXPIRE_MINUTES} min)")
    return otp


def verify_otp(user: User, submitted_otp: str) -> tuple[bool, str]:
    """
    Verify the submitted OTP against the stored value.

    Returns:
        (True, "ok")                 — OTP is valid
        (False, "expired")           — OTP has expired
        (False, "invalid")           — OTP code doesn't match
        (False, "no_otp")            — No OTP exists for this user
    """
    if not user.otp_code or not user.otp_expiry:
        return False, "no_otp"

    # Ensure offset-aware comparison
    expiry = user.otp_expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) > expiry:
        logger.info(f"OTP expired for user_id={user.id}")
        return False, "expired"

    if user.otp_code != submitted_otp.strip():
        logger.warning(f"Invalid OTP attempt for user_id={user.id}")
        return False, "invalid"

    return True, "ok"


def clear_otp(user: User, db: Session) -> None:
    """Remove OTP from user record after successful use."""
    user.otp_code = None
    user.otp_expiry = None
    db.commit()
    logger.info(f"OTP cleared for user_id={user.id}")
