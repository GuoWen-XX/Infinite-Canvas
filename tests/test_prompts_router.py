import os
import sys
import unittest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
import routers.prompts as prompts_module

class TestPromptsRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_get_prompt_templates(self):
        resp = self.client.get("/api/smart-canvas/prompt-templates")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("templates", data)
        self.assertIn("source", data)
        self.assertIsInstance(data["templates"], list)

    def test_02_get_prompt_libraries(self):
        resp = self.client.get("/api/prompt-libraries")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("library", data)
        lib = data["library"]
        self.assertIn("libraries", lib)
        self.assertIn("active_library_id", lib)
        self.assertIsInstance(lib["libraries"], list)

    def test_03_library_lifecycle(self):
        # Create library
        create_resp = self.client.post("/api/prompt-libraries", json={"name": "Test Prompts Alpha"})
        self.assertEqual(create_resp.status_code, 200)
        c_data = create_resp.json()
        lib_obj = c_data.get("prompt_library")
        self.assertIsNotNone(lib_obj)
        lib_id = lib_obj["id"]
        self.assertEqual(lib_obj["name"], "Test Prompts Alpha")

        # Rename library
        rename_resp = self.client.patch(f"/api/prompt-libraries/{lib_id}", json={"name": "Test Prompts Beta"})
        self.assertEqual(rename_resp.status_code, 200)
        r_data = rename_resp.json()
        self.assertEqual(r_data["prompt_library"]["name"], "Test Prompts Beta")

        # System library cannot be deleted
        del_sys = self.client.delete("/api/prompt-libraries/system")
        self.assertEqual(del_sys.status_code, 400)

        # Delete custom library
        del_resp = self.client.delete(f"/api/prompt-libraries/{lib_id}")
        self.assertEqual(del_resp.status_code, 200)

    def test_04_category_and_items_lifecycle(self):
        # Add category
        cat_resp = self.client.post("/api/prompt-libraries/categories", json={"name": "Custom Category", "library_id": "system"})
        self.assertEqual(cat_resp.status_code, 200)
        cat = cat_resp.json().get("category")
        self.assertIsNotNone(cat)
        cat_id = cat["id"]
        self.assertEqual(cat["name"], "Custom Category")

        # Rename category
        ren_cat = self.client.patch(f"/api/prompt-libraries/categories/{cat_id}", json={"name": "Renamed Category"})
        self.assertEqual(ren_cat.status_code, 200)

        # Add item
        item_resp = self.client.post("/api/prompt-libraries/items", json={
            "library_id": "system",
            "name": "Test Item",
            "category": cat_id,
            "positive": "masterpiece, best quality, cyberpunk city",
            "negative": "low quality, blurry",
            "scene": "night cityscape"
        })
        self.assertEqual(item_resp.status_code, 200)
        item = item_resp.json().get("item")
        self.assertIsNotNone(item)
        item_id = item["id"]
        self.assertEqual(item["name"], "Test Item")

        # Update item
        up_resp = self.client.patch(f"/api/prompt-libraries/items/{item_id}", json={
            "library_id": "system",
            "name": "Test Item Updated",
            "category": cat_id,
            "positive": "masterpiece, 8k, cyberpunk street",
            "negative": "lowres",
            "scene": "rainy night"
        })
        self.assertEqual(up_resp.status_code, 200)
        self.assertEqual(up_resp.json()["item"]["name"], "Test Item Updated")

        # Delete item
        del_item = self.client.delete(f"/api/prompt-libraries/items/{item_id}")
        self.assertEqual(del_item.status_code, 200)

        # Batch delete items test
        item_resp2 = self.client.post("/api/prompt-libraries/items", json={
            "library_id": "system",
            "name": "Batch Test Item",
            "category": cat_id,
            "positive": "beautiful flowers",
            "negative": "ugly",
            "scene": "garden"
        })
        self.assertEqual(item_resp2.status_code, 200)
        batch_id = item_resp2.json()["item"]["id"]

        batch_del = self.client.post("/api/prompt-libraries/items/delete", json={"ids": [batch_id]})
        self.assertEqual(batch_del.status_code, 200)
        self.assertEqual(batch_del.json().get("removed"), 1)

        # Delete category
        del_cat = self.client.delete(f"/api/prompt-libraries/categories/{cat_id}")
        self.assertEqual(del_cat.status_code, 200)

if __name__ == "__main__":
    unittest.main()
