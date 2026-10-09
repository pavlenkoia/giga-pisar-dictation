import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class GioIpcTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session unavailable")
    def test_no_instance_refusal_and_remote_command_delivery(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            ready = Path(tmp) / "ready"
            received = Path(tmp) / "received"
            script = Path(__file__).with_name("ipc_scenario.py")
            result = subprocess.run(["dbus-run-session", "--", sys.executable, str(script), str(root), str(ready), str(received)],
                                    text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__": unittest.main()
