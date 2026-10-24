"""Concurrency regression tests for the canvas save transaction (P0 fix).

Guards the invariant that ``PUT /api/canvases/{id}`` performs an atomic
load -> optimistic-version-check -> save under a single hold of CANVAS_LOCK:
when several stations save concurrently from the *same* base version, exactly
one write may win; every other writer must observe the winner's bumped
updated_at and receive HTTP 409 (which drives the client merge/retry path)
rather than silently clobbering the winner (lost update).
"""

import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app


def _put_payload(node_id, base_updated_at):
    return {
        "title": "Concurrency Test Canvas",
        "icon": "layers",
        "nodes": [{"id": node_id, "type": "note", "x": 0, "y": 0}],
        "connections": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
        "logs": [],
        "settings": {},
        "client_id": f"station-{node_id}",
        "base_updated_at": base_updated_at,
    }


class TestCanvasSaveConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        resp = cls.client.post("/api/canvases", json={"title": "Concurrency Test Canvas", "kind": "classic"})
        assert resp.status_code == 200, resp.text
        cls.canvas = resp.json()["canvas"]
        cls.canvas_id = cls.canvas["id"]

    @classmethod
    def tearDownClass(cls):
        try:
            cls.client.delete(f"/api/canvases/{cls.canvas_id}")
            cls.client.delete(f"/api/canvases/{cls.canvas_id}/purge")
        except Exception:
            pass

    def test_stale_base_updated_at_is_rejected_with_409(self):
        """A save carrying an older base_updated_at than the stored one must 409."""
        import time
        current = self.client.get(f"/api/canvases/{self.canvas_id}").json()["canvas"]
        base = int(current.get("updated_at") or 0)
        # Ensure the next save lands in a strictly later millisecond so the version
        # provably advances (guards against the ms-granularity edge, Bug 3).
        time.sleep(0.01)
        # First save advances the version.
        r1 = self.client.put(f"/api/canvases/{self.canvas_id}", json=_put_payload("n-a", base))
        self.assertEqual(r1.status_code, 200, r1.text)
        new_version = int(r1.json()["canvas"]["updated_at"])
        self.assertGreaterEqual(new_version, base)
        # A second save that still references the OLD base must be rejected.
        r2 = self.client.put(f"/api/canvases/{self.canvas_id}", json=_put_payload("n-b", base))
        self.assertEqual(r2.status_code, 409, r2.text)
        detail = r2.json()["detail"]
        self.assertIn("canvas", detail)
        self.assertEqual(int(detail["updated_at"]), new_version)

    def test_concurrent_same_base_saves_have_single_winner(self):
        """Many stations saving from the same base concurrently: exactly one 200,
        the rest 409 (atomic check-and-set — no two writers both pass the guard)."""
        meta = self.client.get(f"/api/canvases/{self.canvas_id}").json()["canvas"]
        base = int(meta.get("updated_at") or 0)

        def do_save(i):
            return self.client.put(
                f"/api/canvases/{self.canvas_id}", json=_put_payload(f"race-{i}", base)
            ).status_code

        with ThreadPoolExecutor(max_workers=8) as ex:
            codes = list(ex.map(do_save, range(8)))

        winners = [c for c in codes if c == 200]
        conflicts = [c for c in codes if c == 409]
        self.assertEqual(len(winners), 1, f"expected exactly one winner, got codes={codes}")
        self.assertEqual(len(winners) + len(conflicts), len(codes), f"unexpected codes={codes}")

        # Final persisted state must be exactly one winner's single node — never a
        # half-merged or clobbered set that lost the winner's write.
        final = self.client.get(f"/api/canvases/{self.canvas_id}").json()["canvas"]
        self.assertEqual(len(final["nodes"]), 1, final["nodes"])
        self.assertTrue(final["nodes"][0]["id"].startswith("race-"))


if __name__ == "__main__":
    unittest.main()
