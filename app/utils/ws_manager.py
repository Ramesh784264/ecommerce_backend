"""
WebSocket Connection Manager

Manages all active WebSocket connections in memory.

Architecture:
  - Connections keyed by user_id (one socket per user)
  - Admin broadcast channel for store-wide events
  - Room-based model: each order has its own "room" for tracking

Thread safety:
  - For single-process Uvicorn (development/small prod): dict is fine
  - For multi-worker production: replace `_connections` with Redis pub/sub
    (each worker only knows its own connections; use Redis to fan out)

Usage:
  ws_manager = WebSocketManager()
  await ws_manager.connect(user_id, websocket)
  await ws_manager.send_to_user(user_id, {"type": "order_update", "data": {...}})
  await ws_manager.broadcast_admins({"type": "new_order", "data": {...}})
"""

import json
import logging
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        # user_id → WebSocket
        self._user_connections: dict[int, WebSocket] = {}
        # Set of user_ids who are admins (for admin broadcasts)
        self._admin_connections: set[int] = set()

    # ── Connection lifecycle ───────────────────────────────────────────────────

    async def connect(self, user_id: int, websocket: WebSocket, is_admin: bool = False) -> None:
        """Accept a new WebSocket connection, replacing any existing one for this user."""
        await websocket.accept()

        # If user already has a connection, close the old one gracefully
        if user_id in self._user_connections:
            try:
                await self._user_connections[user_id].close(code=1008)
            except Exception:
                pass

        self._user_connections[user_id] = websocket

        if is_admin:
            self._admin_connections.add(user_id)

        logger.info(
            f"WebSocket connected: user_id={user_id}, admin={is_admin}, "
            f"total_connections={len(self._user_connections)}"
        )

    def disconnect(self, user_id: int) -> None:
        """Remove a user's connection on disconnect."""
        self._user_connections.pop(user_id, None)
        self._admin_connections.discard(user_id)
        logger.info(
            f"WebSocket disconnected: user_id={user_id}, "
            f"total_connections={len(self._user_connections)}"
        )

    # ── Sending messages ──────────────────────────────────────────────────────

    async def send_to_user(self, user_id: int, payload: dict) -> bool:
        """
        Send a JSON message to a specific user.
        Returns True if sent, False if the user is not connected.
        """
        ws = self._user_connections.get(user_id)
        if not ws:
            return False
        try:
            await ws.send_text(json.dumps(payload))
            return True
        except Exception as e:
            logger.warning(f"Failed to send WS message to user {user_id}: {e}")
            self.disconnect(user_id)
            return False

    async def broadcast_admins(self, payload: dict) -> int:
        """
        Broadcast a message to ALL connected admins.
        Returns the number of admins successfully notified.
        """
        sent = 0
        failed = []
        for admin_id in list(self._admin_connections):
            ws = self._user_connections.get(admin_id)
            if ws:
                try:
                    await ws.send_text(json.dumps(payload))
                    sent += 1
                except Exception as e:
                    logger.warning(f"Failed to broadcast to admin {admin_id}: {e}")
                    failed.append(admin_id)

        for admin_id in failed:
            self.disconnect(admin_id)

        return sent

    async def broadcast_all(self, payload: dict) -> int:
        """
        Broadcast to ALL connected users (use sparingly — stock updates, announcements).
        Returns the number of users successfully notified.
        """
        sent = 0
        failed = []
        for user_id, ws in list(self._user_connections.items()):
            try:
                await ws.send_text(json.dumps(payload))
                sent += 1
            except Exception as e:
                logger.warning(f"Failed to broadcast to user {user_id}: {e}")
                failed.append(user_id)

        for user_id in failed:
            self.disconnect(user_id)

        return sent

    # ── Utility ───────────────────────────────────────────────────────────────

    def is_connected(self, user_id: int) -> bool:
        return user_id in self._user_connections

    @property
    def active_count(self) -> int:
        return len(self._user_connections)

    @property
    def admin_count(self) -> int:
        return len(self._admin_connections)


# ── Singleton instance ────────────────────────────────────────────────────────
# Import this from anywhere in the app:
#   from app.utils.ws_manager import ws_manager
ws_manager = WebSocketManager()
