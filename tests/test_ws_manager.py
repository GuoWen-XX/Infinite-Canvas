import sys
import os
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ws_manager import SafeConnectionManager


class WebSocketManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_disconnect_lifecycle(self):
        mgr = SafeConnectionManager(max_active_connections=5, max_per_client=2)
        mock_ws = AsyncMock()

        accepted = await mgr.connect(mock_ws, client_id="user-1")
        self.assertTrue(accepted)
        self.assertEqual(len(mgr.active_connections), 1)
        mock_ws.accept.assert_awaited_once()

        await mgr.disconnect(mock_ws, client_id="user-1")
        self.assertEqual(len(mgr.active_connections), 0)

    async def test_max_total_connections_guard(self):
        mgr = SafeConnectionManager(max_active_connections=2, max_per_client=5)
        ws1, ws2, ws3 = AsyncMock(), AsyncMock(), AsyncMock()

        self.assertTrue(await mgr.connect(ws1, client_id="u1"))
        self.assertTrue(await mgr.connect(ws2, client_id="u2"))

        # 3rd connection exceeds max_active_connections=2
        accepted = await mgr.connect(ws3, client_id="u3")
        self.assertFalse(accepted)
        ws3.close.assert_awaited_once()
        self.assertEqual(len(mgr.active_connections), 2)

    async def test_max_per_client_guard(self):
        mgr = SafeConnectionManager(max_active_connections=10, max_per_client=2)
        ws1, ws2, ws3 = AsyncMock(), AsyncMock(), AsyncMock()

        self.assertTrue(await mgr.connect(ws1, client_id="heavy-user"))
        self.assertTrue(await mgr.connect(ws2, client_id="heavy-user"))

        # 3rd connection for same client
        accepted = await mgr.connect(ws3, client_id="heavy-user")
        self.assertFalse(accepted)
        ws3.close.assert_awaited_once()
        self.assertEqual(len(mgr.active_connections), 2)


if __name__ == "__main__":
    unittest.main()
