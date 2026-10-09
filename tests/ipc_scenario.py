"""Runs no-owner and remote Gio invocations on a disposable session bus."""
import os
import subprocess
import sys
import time
from pathlib import Path

root, ready, received = map(Path, sys.argv[1:4])
env = dict(os.environ, PYTHONPATH=str(root / "src"))
no_owner = subprocess.run([sys.executable, "-m", "giga_pisar_dictation", "start"], env=env, text=True, capture_output=True, timeout=5)
assert no_owner.returncode != 0
assert "no recording started" in no_owner.stdout.lower()
owner = subprocess.Popen([sys.executable, str(root / "tests" / "ipc_fixture.py"), str(ready), str(received)], env=env)
try:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not ready.exists(): time.sleep(0.02)
    assert ready.exists(), "Gio owner did not register"
    result = subprocess.run([sys.executable, "-m", "giga_pisar_dictation", "status"], env=env, text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr + result.stdout
    assert received.exists(), f"owner did not receive IPC; cli output={result.stdout!r}, error={result.stderr!r}"
    assert received.read_text() == "status"
finally:
    owner.terminate()
    try: owner.wait(timeout=3)
    except subprocess.TimeoutExpired: owner.kill()
