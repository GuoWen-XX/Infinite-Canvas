import os
import sys
import json
import shutil
import unittest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
import routers.assets as assets_module

class TestAssetsRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_get_asset_library(self):
        resp = self.client.get("/api/asset-library")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("library", data)
        lib = data["library"]
        self.assertIn("libraries", lib)
        self.assertIn("active_library_id", lib)
        self.assertTrue(isinstance(lib["libraries"], list))

    def test_02_create_and_rename_library(self):
        # Create library
        create_resp = self.client.post("/api/asset-library/libraries", json={"name": "Test Lib Alpha"})
        self.assertEqual(create_resp.status_code, 200)
        c_data = create_resp.json()
        lib_obj = c_data.get("asset_library")
        self.assertIsNotNone(lib_obj)
        lib_id = lib_obj["id"]
        self.assertEqual(lib_obj["name"], "Test Lib Alpha")

        # Rename library
        rename_resp = self.client.patch(f"/api/asset-library/libraries/{lib_id}", json={"name": "Test Lib Beta"})
        self.assertEqual(rename_resp.status_code, 200)
        r_data = rename_resp.json()
        self.assertEqual(r_data["asset_library"]["name"], "Test Lib Beta")

        # Delete library
        del_resp = self.client.delete(f"/api/asset-library/libraries/{lib_id}")
        self.assertEqual(del_resp.status_code, 200)

    def test_03_category_lifecycle(self):
        # Create category in default library
        cat_resp = self.client.post("/api/asset-library/categories", json={"name": "Test Category 1", "type": "image", "library_id": "default"})
        self.assertEqual(cat_resp.status_code, 200)
        cat = cat_resp.json().get("category")
        self.assertIsNotNone(cat)
        cat_id = cat["id"]
        self.assertEqual(cat["name"], "Test Category 1")

        # Rename category
        rename_resp = self.client.patch(f"/api/asset-library/categories/{cat_id}", json={"name": "Renamed Cat 1", "library_id": "default"})
        self.assertEqual(rename_resp.status_code, 200)
        self.assertEqual(rename_resp.json()["category"]["name"], "Renamed Cat 1")

        # Delete category
        del_resp = self.client.delete(f"/api/asset-library/categories/{cat_id}?library_id=default")
        self.assertEqual(del_resp.status_code, 200)

    def test_04_storage_settings_and_files(self):
        # Get storage settings
        resp = self.client.get("/api/storage-settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("dirs", data)
        self.assertIn("defaults", data)

        # List storage files
        files_resp = self.client.get("/api/storage-files?kind=generated&limit=10")
        self.assertEqual(files_resp.status_code, 200)
        f_data = files_resp.json()
        self.assertIn("items", f_data)
        self.assertTrue(isinstance(f_data["items"], list))

    def test_05_canvas_assets_endpoints(self):
        # Check assets existence
        check_resp = self.client.post("/api/canvas-assets/check", json={"urls": ["/output/nonexistent_file_12345.png"]})
        self.assertEqual(check_resp.status_code, 200)
        data = check_resp.json()
        self.assertIn("exists", data)
        self.assertFalse(data["exists"]["/output/nonexistent_file_12345.png"])

    def test_06_shared_folders_lifecycle(self):
        # Create a temp folder to share inside project root (required by security sandbox)
        temp_dir = os.path.join(assets_module.BASE_DIR, "assets", "test_shared_unit")
        os.makedirs(temp_dir, exist_ok=True)
        try:
            sample_file = os.path.join(temp_dir, "test_sample.png")
            with open(sample_file, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

            # Register shared folder
            reg_resp = self.client.post("/api/shared-folders", json={"path": temp_dir, "name": "Temp Shared Folder"})
            self.assertEqual(reg_resp.status_code, 200)
            folder = reg_resp.json().get("folder")
            self.assertIsNotNone(folder)
            folder_id = folder["id"]

            # List shared folders
            list_resp = self.client.get("/api/shared-folders")
            self.assertEqual(list_resp.status_code, 200)
            f_ids = [f["id"] for f in list_resp.json().get("folders", [])]
            self.assertIn(folder_id, f_ids)

            # Get tree
            tree_resp = self.client.get(f"/api/shared-folders/{folder_id}/tree")
            self.assertEqual(tree_resp.status_code, 200)
            t_data = tree_resp.json()
            self.assertIn("tree", t_data)

            # Unregister shared folder
            unreg_resp = self.client.delete(f"/api/shared-folders/{folder_id}")
            self.assertEqual(unreg_resp.status_code, 200)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_07_local_assets_folder_and_list(self):
        # List local assets
        resp = self.client.get("/api/local-assets")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tree", data)
        self.assertIn("items", data)

        # Create folder
        cf_resp = self.client.post("/api/local-assets/folders", json={"name": "test_unit_folder"}, headers={"origin": "http://testserver"})
        self.assertEqual(cf_resp.status_code, 200)
        self.assertTrue(cf_resp.json().get("ok"))

        # Rename folder
        rf_resp = self.client.patch("/api/local-assets/folders", json={"path": "test_unit_folder", "name": "test_unit_folder_renamed"}, headers={"origin": "http://testserver"})
        self.assertEqual(rf_resp.status_code, 200)
        self.assertTrue(rf_resp.json().get("ok"))

        # Clean up created folder
        target_dir = os.path.join(assets_module.LOCAL_UPLOAD_DIR, "test_unit_folder_renamed")
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir, ignore_errors=True)

    def test_08_asset_classification_prompt(self):
        resp = self.client.get("/api/asset-classification-prompt")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("prompt", data)
        self.assertIn("default_prompt", data)

    def test_09_atomic_save_json(self):
        temp_target = os.path.join(assets_module.BASE_DIR, "assets", f"ic_atomic_test_{os.getpid()}.json")
        try:
            test_data = {"key": "value", "numbers": [1, 2, 3]}
            assets_module.atomic_save_json(temp_target, test_data)
            self.assertTrue(os.path.isfile(temp_target))

            with open(temp_target, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, test_data)
        finally:
            if os.path.exists(temp_target):
                os.remove(temp_target)

if __name__ == "__main__":
    unittest.main()
