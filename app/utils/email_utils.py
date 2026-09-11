"""
Email Notification Utility

Sends transactional emails using SMTP (Gmail / any SMTP provider).
All credentials are read from environment variables.

Supported email types:
  - OTP / Account Verification
  - Forgot Password OTP
  - Order Confirmation
  - Order Status Updates
  - Vendor Approval / Rejection

To use Gmail:
  1. Enable 2-Step Verification on your Google account
  2. Generate an App Password: myaccount.google.com → Security → App Passwords
  3. Set SMTP_PASSWORD to the 16-char App Password (NOT your Gmail password)
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# ── SMTP Config from environment ──────────────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "ShopEase")


def _send_email(to_email: str, subject: str, html_body: str) -> bool:
    """
    Internal SMTP sender.

    Returns True on success, False on any error (so callers can continue
    without crashing — email failure should never block the user).
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — email not sent")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(f"SMTP auth failed — check SMTP_USER and SMTP_PASSWORD in .env")
        return False
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


# ── Email Templates ───────────────────────────────────────────────────────────

def send_otp_email(to_email: str, name: str, otp: str, purpose: str = "verification") -> bool:
    """
    Send an OTP email for account verification or forgot-password.

    Args:
        purpose: "verification" | "password_reset"
    """
    if purpose == "password_reset":
        title = "Reset Your Password"
        desc = "You requested a password reset. Use the OTP below to set a new password."
    else:
        title = "Verify Your Email Address"
        desc = "Welcome! Please verify your email address using the OTP below."

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background:#f4f4f4; margin:0; padding:20px;">
      <div style="max-width:520px; margin:0 auto; background:#fff; border-radius:12px;
                  box-shadow:0 2px 12px rgba(0,0,0,0.08); overflow:hidden;">
        <div style="background:linear-gradient(135deg,#6C63FF,#3B82F6); padding:32px; text-align:center;">
          <h1 style="color:#fff; margin:0; font-size:24px;">🛒 ShopEase</h1>
        </div>
        <div style="padding:36px 32px;">
          <h2 style="color:#1e293b; margin-top:0;">{title}</h2>
          <p style="color:#475569;">Hi <strong>{name}</strong>,</p>
          <p style="color:#475569;">{desc}</p>
          <div style="background:#f8fafc; border:2px dashed #6C63FF; border-radius:10px;
                      padding:24px; text-align:center; margin:28px 0;">
            <p style="color:#64748b; font-size:13px; margin:0 0 8px;">Your OTP Code</p>
            <h1 style="color:#6C63FF; font-size:42px; letter-spacing:12px; margin:0;
                        font-weight:800;">{otp}</h1>
          </div>
          <p style="color:#94a3b8; font-size:13px;">
            ⏱ This OTP expires in <strong>10 minutes</strong>.<br>
            If you didn't request this, please ignore this email.
          </p>
        </div>
        <div style="background:#f8fafc; padding:20px; text-align:center; border-top:1px solid #e2e8f0;">
          <p style="color:#94a3b8; font-size:12px; margin:0;">
            © 2026 ShopEase. All rights reserved.
          </p>
        </div>
      </div>
    </body>
    </html>
    """
    return _send_email(to_email, f"Your {title} OTP — ShopEase", html)


def send_order_confirmation_email(
    to_email: str, name: str, order_id: int, total_amount: float, items: list[dict]
) -> bool:
    """Send order confirmation email after successful checkout or payment."""
    items_html = "".join(
        f"<tr>"
        f"<td style='padding:10px 0; border-bottom:1px solid #f1f5f9; color:#334155;'>{item['name']}</td>"
        f"<td style='padding:10px 0; border-bottom:1px solid #f1f5f9; text-align:center; color:#334155;'>×{item['quantity']}</td>"
        f"<td style='padding:10px 0; border-bottom:1px solid #f1f5f9; text-align:right; color:#334155;'>₹{item['price']:.2f}</td>"
        f"</tr>"
        for item in items
    )

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family:'Segoe UI',Arial,sans-serif; background:#f4f4f4; margin:0; padding:20px;">
      <div style="max-width:560px; margin:0 auto; background:#fff; border-radius:12px;
                  box-shadow:0 2px 12px rgba(0,0,0,0.08); overflow:hidden;">
        <div style="background:linear-gradient(135deg,#10b981,#059669); padding:32px; text-align:center;">
          <h1 style="color:#fff; margin:0;">✅ Order Confirmed!</h1>
        </div>
        <div style="padding:36px 32px;">
          <p style="color:#475569;">Hi <strong>{name}</strong>, your order has been placed successfully.</p>
          <div style="background:#f0fdf4; border-left:4px solid #10b981; padding:16px; border-radius:6px; margin:20px 0;">
            <p style="margin:0; color:#166534; font-size:14px;">
              Order ID: <strong>#{order_id}</strong>
            </p>
          </div>
          <table style="width:100%; border-collapse:collapse;">
            <thead>
              <tr style="border-bottom:2px solid #e2e8f0;">
                <th style="text-align:left; padding:10px 0; color:#94a3b8; font-size:12px; text-transform:uppercase;">Product</th>
                <th style="text-align:center; padding:10px 0; color:#94a3b8; font-size:12px; text-transform:uppercase;">Qty</th>
                <th style="text-align:right; padding:10px 0; color:#94a3b8; font-size:12px; text-transform:uppercase;">Price</th>
              </tr>
            </thead>
            <tbody>{items_html}</tbody>
          </table>
          <div style="border-top:2px solid #1e293b; margin-top:16px; padding-top:16px; text-align:right;">
            <strong style="font-size:18px; color:#1e293b;">Total: ₹{total_amount:.2f}</strong>
          </div>
          <p style="color:#64748b; font-size:13px; margin-top:24px;">
            We'll send you another email when your order ships. 🚚
          </p>
        </div>
      </div>
    </body>
    </html>
    """
    return _send_email(to_email, f"Order #{order_id} Confirmed — ShopEase", html)


def send_order_status_email(
    to_email: str, name: str, order_id: int, new_status: str
) -> bool:
    """Send email when order status changes (shipped, delivered, cancelled, etc.)."""
    status_map = {
        "confirmed":  ("✅ Order Confirmed",   "#10b981", "Your order has been confirmed and is being prepared."),
        "shipped":    ("🚚 Order Shipped",     "#3B82F6", "Your order is on its way! Track it using your order ID."),
        "delivered":  ("🎉 Order Delivered",   "#8B5CF6", "Your order has been delivered. Enjoy your purchase!"),
        "cancelled":  ("❌ Order Cancelled",   "#ef4444", "Your order has been cancelled. Refund (if applicable) will be processed shortly."),
    }
    emoji, color, message = status_map.get(
        new_status, ("📦 Order Update", "#64748b", f"Your order status has been updated to: {new_status}.")
    )

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family:'Segoe UI',Arial,sans-serif; background:#f4f4f4; margin:0; padding:20px;">
      <div style="max-width:520px; margin:0 auto; background:#fff; border-radius:12px;
                  box-shadow:0 2px 12px rgba(0,0,0,0.08); overflow:hidden;">
        <div style="background:{color}; padding:32px; text-align:center;">
          <h1 style="color:#fff; margin:0;">{emoji}</h1>
        </div>
        <div style="padding:36px 32px;">
          <p style="color:#475569;">Hi <strong>{name}</strong>,</p>
          <p style="color:#475569;">{message}</p>
          <div style="background:#f8fafc; border-radius:8px; padding:16px; margin:20px 0;">
            <p style="margin:0; color:#64748b;">Order ID: <strong style="color:#1e293b;">#{order_id}</strong></p>
            <p style="margin:6px 0 0; color:#64748b;">Status: <strong style="color:{color};">{new_status.upper()}</strong></p>
          </div>
        </div>
      </div>
    </body>
    </html>
    """
    return _send_email(to_email, f"Order #{order_id} — {emoji} — ShopEase", html)


def send_vendor_decision_email(
    to_email: str, name: str, shop_name: str, approved: bool, reason: str = ""
) -> bool:
    """Notify vendor when their application is approved or rejected."""
    if approved:
        subject = "🎉 Your Vendor Application is Approved!"
        color = "#10b981"
        body = f"""
          <p>Congratulations <strong>{name}</strong>! Your shop <strong>"{shop_name}"</strong>
          has been approved on ShopEase.</p>
          <p>You can now log in and start listing your products.</p>
        """
    else:
        subject = "Your Vendor Application — Update"
        color = "#ef4444"
        reason_html = f"<p><strong>Reason:</strong> {reason}</p>" if reason else ""
        body = f"""
          <p>Hi <strong>{name}</strong>, unfortunately your vendor application for
          <strong>"{shop_name}"</strong> has not been approved at this time.</p>
          {reason_html}
          <p>You may re-apply after addressing the concerns mentioned above.</p>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family:'Segoe UI',Arial,sans-serif; background:#f4f4f4; margin:0; padding:20px;">
      <div style="max-width:520px; margin:0 auto; background:#fff; border-radius:12px;
                  box-shadow:0 2px 12px rgba(0,0,0,0.08); overflow:hidden;">
        <div style="background:{color}; padding:32px; text-align:center;">
          <h1 style="color:#fff; margin:0;">ShopEase Vendor Portal</h1>
        </div>
        <div style="padding:36px 32px;">
          {body}
        </div>
      </div>
    </body>
    </html>
    """
    return _send_email(to_email, subject, html)
