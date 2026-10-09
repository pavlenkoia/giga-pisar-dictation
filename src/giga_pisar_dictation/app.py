"""Gio single-instance command routing without implicit recording."""
from __future__ import annotations
import json

APP_ID = "org.gigapisar.Dictation"
COMMANDS = {"start", "stop", "cancel", "status", "toggle"}


def parse_command(arguments):
    command = arguments[0] if arguments else "toggle"
    if command not in COMMANDS: raise ValueError("Unknown command")
    return command


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
        if not command_line.get_is_remote():
            if not args and self.on_launch:
                self.on_launch()
                return 0
            command_line.print_literal("No running Giga Pisar Dictation instance; no recording started.\n")
            return 1
        try:
            command = parse_command(args)
            result = self.on_command(command)
            command_line.print_literal(json.dumps(result if result is not None else {"ok": True}) + "\n")
            return 0
        except ValueError:
            command_line.print_literal("Unknown command.\n")
            return 2

    def run(self, argv):
        return self.application.run(argv)
