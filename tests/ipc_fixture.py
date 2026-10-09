"""Isolated D-Bus fixture used only by test_ipc_dbus."""
import sys
from pathlib import Path
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from giga_pisar_dictation.app import APP_ID

ready, received = map(Path, sys.argv[1:3])
app = Gio.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

def command_line(application, command_line):
    args = command_line.get_arguments()[1:]
    if not command_line.get_is_remote():
        application.hold(); ready.write_text("ready")
        return 0
    received.write_text(" ".join(args))
    command_line.print_literal('{"ok":true}\n')
    return 0

app.connect("command-line", command_line)
app.run([sys.argv[0]])
