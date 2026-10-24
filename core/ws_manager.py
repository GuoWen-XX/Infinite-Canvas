import json
import logging
from typing import List, Dict, Optional
from fastapi import WebSocket

logger = logging.getLogger("infinite_canvas.ws")


class SafeConnectionManager:
    """Hardened WebSocket connection manager with active limits against DoS attacks."""

    def __init__(self, max_active_connections: int = 200, max_per_client: int = 15):
        self.max_active_connections = max_active_connections
        self.max_per_client = max_per_client

        self.active_connections: List[WebSocket] = []
        self.user_connections: Dict[str, WebSocket] = {}
        self.connection_clients: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, client_id: Optional[str] = None) -> bool:
        """Accept connection with capacity guard. Returns True if accepted, False if rejected."""
        cid = client_id or f"anon-{id(websocket)}"

        # Guard 1: Total active connection limit
        if len(self.active_connections) >= self.max_active_connections:
            logger.warning(f"Rejecting WS: max active connections ({self.max_active_connections}) reached")
            try:
                await websocket.close(code=1008, reason="Server connection limit reached")
            except Exception:
                pass
            return False

        # Guard 2: Per-client connection limit
        client_count = sum(1 for c in self.connection_clients.values() if c == cid)
        if client_count >= self.max_per_client:
            logger.warning(f"Rejecting WS: client {cid} reached max connections ({self.max_per_client})")
            try:
                await websocket.close(code=1008, reason="Client connection limit reached")
            except Exception:
                pass
            return False

        await websocket.accept()
        self.active_connections.append(websocket)
        self.connection_clients[websocket] = cid
        if client_id:
            self.user_connections[client_id] = websocket

        logger.info(f"WS Connected. Total: {len(self.active_connections)}, Online: {self.online_count()}")
        await self.broadcast_count()
        return True

    def _remove_connection(self, connection: WebSocket) -> None:
        if connection in self.active_connections:
            self.active_connections.remove(connection)
        self.connection_clients.pop(connection, None)
        for cid, ws in list(self.user_connections.items()):
            if ws is connection:
                self.user_connections.pop(cid, None)

    async def disconnect(self, websocket: WebSocket, client_id: Optional[str] = None) -> None:
        self._remove_connection(websocket)
        if client_id and client_id in self.user_connections:
            self.user_connections.pop(client_id, None)

        logger.info(f"WS Disconnected. Total: {len(self.active_connections)}, Online: {self.online_count()}")
        await self.broadcast_count()

    def online_count(self) -> int:
        visible_clients = {
            cid for cid in self.connection_clients.values()
            if cid and not str(cid).startswith("canvas_")
        }
        return len(visible_clients)

    async def broadcast_count(self) -> None:
        count = self.online_count()
        data = json.dumps({"type": "stats", "online_count": count})
        await self._broadcast_raw(data)

    async def broadcast_new_image(self, image_data: dict) -> None:
        data = json.dumps({"type": "new_image", "data": image_data})
        await self._broadcast_raw(data)

    async def broadcast_canvas_updated(self, canvas_id: str, updated_at: int, client_id: str = "") -> None:
        data = json.dumps({
            "type": "canvas_updated",
            "canvas_id": canvas_id,
            "updated_at": updated_at,
            "client_id": client_id or "",
        })
        await self._broadcast_raw(data)

    async def broadcast_asset_library_updated(self, updated_at: int = 0) -> None:
        import time
        data = json.dumps({
            "type": "asset_library_updated",
            "updated_at": updated_at or int(time.time() * 1000),
        })
        await self._broadcast_raw(data)

    async def broadcast_cursor(self, payload: dict, sender_ws: Optional[WebSocket] = None) -> None:
        data = json.dumps(payload)
        for connection in self.active_connections[:]:
            if sender_ws is not None and connection is sender_ws:
                continue
            try:
                await connection.send_text(data)
            except Exception as exc:
                logger.debug(f"WS Cursor broadcast error, removing stale client: {exc}")
                self._remove_connection(connection)

    async def broadcast_rhino_capture(self, capture_data: dict) -> None:
        data = json.dumps({
            "type": "rhino_capture",
            "data": capture_data,
        })
        await self._broadcast_raw(data)

    async def broadcast_mobile_push(self, push_data: dict) -> None:
        data = json.dumps({
            "type": "mobile_push_image",
            "data": push_data,
        })
        await self._broadcast_raw(data)

    async def send_personal_message(self, message: dict, client_id: str) -> None:
        ws = self.user_connections.get(client_id)
        if ws:
            try:
                await ws.send_text(json.dumps(message))
            except Exception as exc:
                logger.debug(f"Personal message error for {client_id}: {exc}")

    async def _broadcast_raw(self, payload: str) -> None:
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(payload)
            except Exception as exc:
                logger.debug(f"WS Broadcast error, removing stale client: {exc}")
                self._remove_connection(connection)
