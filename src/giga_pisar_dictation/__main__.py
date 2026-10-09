"""Command line entry point for the GTK desktop app and Gio IPC."""
import argparse
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        class RussianArgumentParser(argparse.ArgumentParser):
            def error(self, message):
                self.print_usage(sys.stderr)
                self.exit(2, f"{self.prog}: ошибка: неверные аргументы\n")

            def format_usage(self):
                return super().format_usage().replace("usage:", "использование:")

            def format_help(self):
                text = super().format_help()
                return (text.replace("usage:", "использование:").replace("positional arguments", "позиционные аргументы")
                        .replace("options:", "параметры:").replace("show this help message and exit", "показать эту справку и выйти"))
        parser = RussianArgumentParser(description="Русский клиент диктовки «Гига Писарь»")
        parser.add_argument("command", nargs="?", choices=("start", "stop", "cancel", "status", "toggle"), default="toggle",
                            help="команда управления (по умолчанию: toggle)")
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
                dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.NONE,
                                           text="Не удалось прочитать настройки приложения")
                dialog.add_button("Закрыть", Gtk.ResponseType.CLOSE)
                dialog.format_secondary_text("Проверьте владельца и права доступа к закрытым файлам настроек.")
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
        print("Не удалось связаться с графическим сеансом или запущенным приложением.", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
