"""Runs no-owner and remote Gio invocations on a disposable session bus."""
import os
import subprocess
import sys
import time
from pathlib import Path

root, ready, received = map(Path, sys.argv[1:4])
sys.path.insert(0, str(root / "src"))
env = dict(os.environ, PYTHONPATH=str(root / "src"))
for command in ("start", "status", "toggle"):
    no_owner = subprocess.run([sys.executable, "-m", "giga_pisar_dictation", command], env=env, text=True, capture_output=True, timeout=5)
    assert no_owner.returncode != 0
    assert "no recording started" in no_owner.stdout.lower()
owner = subprocess.Popen([sys.executable, str(root / "tests" / "ipc_fixture.py"), str(ready), str(received)], env=env)
try:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not ready.exists(): time.sleep(0.02)
    assert ready.exists(), "Gio owner did not register"
    from giga_pisar_dictation.app import parse_launch
    assert parse_launch([]) == ("ordinary", None)
    assert parse_launch(["--autostart"]) == ("autostart", None)
    for args, expected in (([], "command:show\n"), (["toggle"], "command:toggle\n"), (["status"], "command:status\n")):
        before = received.read_text() if received.exists() else ""
        result = subprocess.run([sys.executable, "-m", "giga_pisar_dictation", *args], env=env, text=True, capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr + result.stdout
        assert received.read_text() == before + expected, (args, received.read_text())
    before = received.read_text()
    result = subprocess.run([sys.executable, "-m", "giga_pisar_dictation", "--autostart"], env=env, text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr + result.stdout
    assert received.read_text() == before, "repeated autostart invoked a production callback"
finally:
    owner.terminate()
    try: owner.wait(timeout=3)
    except subprocess.TimeoutExpired: owner.kill()
