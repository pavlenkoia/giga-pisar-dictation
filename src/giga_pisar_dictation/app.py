"""Gio single-instance command routing without implicit recording."""
from __future__ import annotations
import json

APP_ID = "org.gigapisar.Dictation"
COMMANDS = {"start", "stop", "cancel", "status", "toggle"}


def parse_command(arguments):
    """Parse an explicit command (legacy empty-list behavior is toggle)."""
    command = arguments[0] if arguments else "toggle"
    if len(arguments) > 1 or command not in COMMANDS:
        raise ValueError("Неизвестная команда")
    return command


def parse_launch(arguments):
    """Return (mode, command): desktop launches differ from explicit IPC commands."""
    if arguments == ["--autostart"]:
        return "autostart", None
    if not arguments:
        return "ordinary", None
    if len(arguments) == 1 and arguments[0] in COMMANDS:
        return None, arguments[0]
    raise ValueError("Неизвестная команда")


class CommandApplication:
    """Launches UI only on an explicit desktop launch; remote commands reach handler."""
    def __init__(self, on_command, on_launch=None):
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        self.on_command, self.on_launch = on_command, on_launch
        self.application = Gio.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.application.connect("command-line", self._command_line)

    def _command_line(self, app, command_line):
        args = command_line.get_arguments()[1:]
        try:
            mode, command = parse_launch(args)
            if not command_line.get_is_remote():
                if mode is not None and self.on_launch:
                    self.on_launch(mode)
                    return 0
                command_line.print_literal("Нет запущенного экземпляра; запись не начата.\n")
                return 1
            if command is None:
                if mode == "ordinary":
                    result = self.on_command("show")
                else:
                    result = {"ok": True, "status": "already running"}
            else:
                result = self.on_command(command)
            command_line.print_literal(json.dumps(result if result is not None else {"ok": True}) + "\n")
            return 0
        except ValueError:
            command_line.print_literal("Неизвестная команда.\n")
            return 2

    def run(self, argv):
        return self.application.run(argv)
