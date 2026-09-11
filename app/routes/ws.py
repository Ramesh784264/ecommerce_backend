"""
WebSocket Routes

Endpoints:
  WS  /ws/connect                    → Authenticated user WebSocket connection
  WS  /ws/admin                      → Admin-only broadcast receiver
  GET /ws/status                     → Connection pool status (admin)

Event types pushed to clients:
  {"type": "order_status_changed",  "data": {"order_id": 1, "status": "shipped"}}
  {"type": "payment_confirmed",     "data": {"order_id": 1, "payment_id": "..."}}
  {"type": "stock_update",          "data": {"product_id": 5, "stock": 12}}
  {"type": "new_order",             "data": {"order_id": 1, "amount": 999.0}}  (admin only)
  {"type": "low_stock_alert",       "data": {"product_id": 5, "stock": 2}}     (admin only)
  {"type": "ping",                  "data": {}}                                (keepalive)

Authentication:
  JWT token passed as query param: ws://host/api/v1/ws/connect?token=<jwt>
  (WebSocket handshake cannot set Authorization headers in browsers)

Keepalive:
  Client should send {"type": "ping"} every 30s.
  Server replies with {"type": "pong"}.
  If no ping for 90s, the server will close the connection.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user_model import User
from app.utils.jwt_handler import decode_access_token
from app.utils.ws_manager import ws_manager
from app.utils.dependencies import role_required

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

PING_TIMEOUT_SECONDS = 90   # Close connection if no ping within this window


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _authenticate_ws(token: str, db: Session) -> User | None:
    """
    Decode JWT from query param and return the User.
    Returns None on any auth failure (caller must close the socket).
    """
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    return user


async def _keepalive_loop(websocket: WebSocket, user_id: int) -> None:
    """
    Receive loop that handles client ping → server pong and detects dead connections.
    Runs until the socket disconnects or the timeout is reached.
    """
    while True:
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=PING_TIMEOUT_SECONDS,
            )
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "data": {}}))

        except asyncio.TimeoutError:
            logger.info(f"WS ping timeout for user_id={user_id}. Closing.")
            await websocket.close(code=1001)  # Going away
            break
        except WebSocketDisconnect:
            break
        except Exception as e:
            logger.warning(f"WS receive error for user_id={user_id}: {e}")
            break


# ─────────────────────────────────────────────────────────────────────────────
# 1. AUTHENTICATED USER CONNECTION
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/connect")
async def ws_connect(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db),
):
    """
    Main WebSocket endpoint for all authenticated users.

    Connect with:
      ws://localhost:8000/api/v1/ws/connect?token=<your-jwt>

    Events you will receive:
      - order_status_changed  (when your orders are updated)
      - payment_confirmed     (when your payment is verified)
      - stock_update          (product stock changed — if you have it in cart/wishlist)

    Keepalive:
      Send {"type": "ping"} every 30 seconds.
      Server responds with {"type": "pong"}.
    """
    user = await _authenticate_ws(token, db)

    if not user:
        await websocket.close(code=4001)   # Custom: unauthorized
        logger.warning("WS connection rejected: invalid/expired token")
        return

    is_admin = user.role == "admin"
    await ws_manager.connect(user.id, websocket, is_admin=is_admin)

    # Send welcome event
    await websocket.send_text(json.dumps({
        "type": "connected",
        "data": {
            "user_id": user.id,
            "name": user.name,
            "role": user.role,
            "message": "WebSocket connected successfully",
        }
    }))

    # If admin, tell them how many users are online
    if is_admin:
        await websocket.send_text(json.dumps({
            "type": "admin_info",
            "data": {
                "active_connections": ws_manager.active_count,
                "admin_connections": ws_manager.admin_count,
            }
        }))

    try:
        await _keepalive_loop(websocket, user.id)
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(user.id)
        logger.info(f"WS cleaned up for user_id={user.id}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. ADMIN-ONLY BROADCAST ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/admin")
async def ws_admin(
    websocket: WebSocket,
    token: str = Query(..., description="Admin JWT token"),
    db: Session = Depends(get_db),
):
    """
    Dedicated admin WebSocket.

    Admins receive all events that customers receive PLUS:
      - new_order         (any new order placed on the store)
      - low_stock_alert   (product stock dropped to <= 5)
      - vendor_applied    (new vendor application)
      - payment_failed    (any payment failure)

    Connect with:
      ws://localhost:8000/api/v1/ws/admin?token=<admin-jwt>
    """
    user = await _authenticate_ws(token, db)

    if not user or user.role != "admin":
        await websocket.close(code=4003)   # Forbidden
        logger.warning(f"Admin WS rejected for user_id={user.id if user else 'unknown'}")
        return

    await ws_manager.connect(user.id, websocket, is_admin=True)

    await websocket.send_text(json.dumps({
        "type": "connected",
        "data": {
            "message": "Admin WebSocket connected",
            "active_connections": ws_manager.active_count,
        }
    }))

    try:
        await _keepalive_loop(websocket, user.id)
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(user.id)


# ─────────────────────────────────────────────────────────────────────────────
# 3. CONNECTION POOL STATUS (REST, admin only)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status")
def ws_status(current_user: User = Depends(role_required("admin"))):
    """
    Returns current WebSocket pool statistics.
    Useful for monitoring dashboards.
    """
    return {
        "active_connections": ws_manager.active_count,
        "admin_connections": ws_manager.admin_count,
        "customer_connections": ws_manager.active_count - ws_manager.admin_count,
    }
