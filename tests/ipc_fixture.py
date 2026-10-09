"""Production Gio router with inert callbacks for isolated IPC tests."""
import sys
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from giga_pisar_dictation.app import CommandApplication

ready, received = sys.argv[1:3]

def on_command(command):
    with open(received, "a", encoding="utf-8") as stream:
        stream.write(f"command:{command}\n")
    return {"ok": True}

def on_launch(mode):
    with open(received, "a", encoding="utf-8") as stream:
        stream.write(f"launch:{mode}\n")

router = CommandApplication(on_command, on_launch)
router.application.connect("startup", lambda app: (app.hold(), open(ready, "w").close()))
router.run([sys.argv[0]])
