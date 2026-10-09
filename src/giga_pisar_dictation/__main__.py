"""Command line entry point for the GTK desktop app and Gio IPC."""
import argparse
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        parser = argparse.ArgumentParser(description="Giga Pisar Dictation desktop client")
        parser.add_argument("command", nargs="?", choices=("start", "stop", "cancel", "status", "toggle"), default="toggle")
        parser.parse_args(argv)
        return 0
    desktop = {}
    try:
        from .app import CommandApplication
        def launch(mode="ordinary"):
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            from .gui import DesktopWindow
            from .desktop import DesktopController
            try:
                window = DesktopWindow(); DesktopController(window); desktop["window"] = window
            except (OSError, ValueError, PermissionError):
                dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                                           text="Unable to read application settings")
                dialog.format_secondary_text("Check the ownership and permissions of the private configuration files.")
                dialog.run(); dialog.destroy()
                return
            from gi.repository import GLib
            GLib.idle_add(window.apply_launch_mode, mode)
            try: Gtk.main()
            finally: window.effects.shutdown()
        def command(name):
            window = desktop.get("window")
            effects = getattr(window, "effects", None)
            if effects is None: return {"ok": False, "status": "desktop unavailable"}
            if name == "show":
                window.window.show_all(); window.window.present()
                return {"ok": True, "status": "shown"}
            return effects.command(name)
        return CommandApplication(command, launch).run([sys.argv[0], *argv])
    except Exception:
        print("Unable to contact the desktop session or running application.", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
