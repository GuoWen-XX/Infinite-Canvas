"""S02 regression: macOS must open the reachable local URL by default.

Mocks all external commands; never starts the server or opens a real browser.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "mac-启动服务.sh"


class MacLauncherTests(unittest.TestCase):
    def test_shell_syntax(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_opens_loopback_even_with_lan_ip(self):
        # LAN is disabled by default and main.py binds 127.0.0.1, even when
        # the workstation has an en0/en1 LAN address.
        with tempfile.TemporaryDirectory() as d:
            bin_dir = Path(d) / "bin"
            bin_dir.mkdir()
            for name, script in {
                "ipconfig": "#!/bin/sh\necho 192.0.2.25\n",
                "sleep": "#!/bin/sh\nexit 0\n",
                "open": "#!/bin/sh\nprintf 'MOCK_OPEN_URL=%s\\n' \"$1\"\n",
                "python3": "#!/bin/sh\nexit 0\n",
            }.items():
                mock = bin_dir / name
                mock.write_text(script, encoding="utf-8")
                mock.chmod(0o755)
            env = os.environ.copy()
            env.pop("INFINITE_CANVAS_LAN", None)
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MOCK_OPEN_URL=http://127.0.0.1:3000/", result.stdout)


if __name__ == "__main__":
    unittest.main()
