"""S08 offline-only wheelhouse release checks using synthetic fixtures."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[1] / "tools" / "check_s08_wheelhouse.py"
_SPEC = importlib.util.spec_from_file_location("s08_wheelhouse", _MODULE)
wheelhouse = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wheelhouse)


class WheelhouseGateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="s08_wheels_")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "packages").mkdir()
        (self.root / "python").mkdir()
        (self.root / "python" / "python310.dll").touch()

    def wheel(self, filename):
        (self.root / "packages" / filename).touch()

    def audit(self, requirements, target=None):
        (self.root / "requirements.txt").write_text(requirements, encoding="utf-8")
        return wheelhouse.audit(self.root / "requirements.txt", self.root / "packages",
                                self.root / "python", target)

    def test_identifies_embedded_python_310(self):
        self.assertEqual(wheelhouse.bundled_python_version(self.root / "python"), "3.10")

    def test_missing_and_wrong_version_are_release_blockers(self):
        self.wheel("fastapi-0.136.1-py3-none-any.whl")
        result = self.audit("fastapi==0.141.1\nPyYAML==6.0.3\n")
        self.assertFalse(result["passed"])
        reasons = {x["name"]: x["reason"] for x in result["problems"]}
        self.assertEqual(reasons, {"fastapi": "version_mismatch", "pyyaml": "missing"})

    def test_cp314_binary_wheel_does_not_satisfy_python310(self):
        self.wheel("pillow-12.3.0-cp314-cp314-win_amd64.whl")
        result = self.audit("pillow==12.3.0\n")
        self.assertFalse(result["passed"])
        self.assertEqual(result["problems"][0]["reason"], "incompatible_wheel_tags")
        self.assertIn("pillow-12.3.0-cp314-cp314-win_amd64.whl",
                      result["incompatible_wheels"])

    def test_exact_pure_and_cp310_wheels_satisfy_static_gate(self):
        self.wheel("fastapi-0.141.1-py3-none-any.whl")
        self.wheel("pillow-12.3.0-cp310-cp310-win_amd64.whl")
        result = self.audit("fastapi==0.141.1\npillow==12.3.0\n")
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["matched"]), 2)

    def test_older_generic_python_wheel_accepted_for_python310(self):
        self.wheel("example-1.2.0-py39-none-any.whl")
        self.assertTrue(self.audit("example==1.2.0\n")["passed"])

    def test_future_generic_python_wheel_rejected(self):
        self.wheel("example-1.2.0-py311-none-any.whl")
        self.assertFalse(self.audit("example==1.2.0\n")["passed"])

    def test_rejects_unpinned_requirements(self):
        with self.assertRaises(ValueError):
            self.audit("fastapi>=0.141.1\n")

    def test_older_abi3_can_support_embedded_python(self):
        self.wheel("example-1.2.0-cp38-abi3-win_amd64.whl")
        result = self.audit("example==1.2.0\n")
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
