"""GTK3 window with Ayatana/AppIndicator tray and visible fallback quit."""
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib


class DesktopWindow:
    def __init__(self):
        self.window = Gtk.Window(title="Giga Pisar Dictation")
        self.window.set_default_size(460, 340)
        self.shortcut_status = Gtk.Label(label="Global shortcut status: starting")
        self.status = Gtk.Label(label="Ready"); self.output = Gtk.TextView()
        self.output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR); self.output.set_editable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); box.set_border_width(12)
        box.pack_start(self.status, False, False, 0); box.pack_start(self.shortcut_status, False, False, 0); box.pack_start(self.output, True, True, 0)
        controls = Gtk.Box(spacing=6)
        for label in ("Start", "Stop", "Cancel", "Copy", "Check server", "Settings", "Quit"):
            button = Gtk.Button(label=label); button.connect("clicked", self._button, label)
            controls.pack_start(button, True, True, 0)
        box.pack_start(controls, False, False, 0); self.window.add(box)
        self.window.connect("delete-event", self._hide)
        self.window.connect("focus-out-event", self._focus_lost)
        self.external_window = None; self.indicator = None
        self._create_indicator()
        self.window.show_all()

    def _create_indicator(self):
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as Indicator
        except (ImportError, ValueError):
            try:
                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3 as Indicator
            except (ImportError, ValueError): return
        try:
            self.Indicator = Indicator
            self.indicator = Indicator.Indicator.new("giga-pisar-dictation", "audio-input-microphone",
                                                      Indicator.IndicatorCategory.APPLICATION_STATUS)
            self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        except Exception:
            self.indicator = None
            self.Indicator = None
            return
        menu = Gtk.Menu()
        for title, command in (("Show window", "show"), ("Toggle recording", "toggle"), ("Start", "start"),
                               ("Stop", "stop"), ("Cancel", "cancel"), ("Status", "status"), ("Quit", "quit")):
            item = Gtk.MenuItem(label=title); item.connect("activate", self._menu_action, command); menu.append(item)
        menu.show_all(); self.indicator.set_menu(menu)

    def _focus_lost(self, *_):
        GLib.timeout_add(120, self._remember_external_window)
        return False

    def _remember_external_window(self):
        x11 = None
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            own = self.window.get_window().get_xid()
            from .x11 import X11Adapter
            x11 = X11Adapter(); target = x11.active_window()
            if target and target != own: self.external_window = target
        except Exception: pass
        finally:
            if x11: x11.close()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        self.status.set_text(self.controller.message)
        self.output.get_buffer().set_text(self.controller.text or "")

    def modifiers_down(self):
        return self.effects.x11.modifiers_down() if self.effects.x11 else True

    def _menu_action(self, _item, command):
        if command == "show": self.window.show_all()
        elif command == "quit": self.quit()
        else: self._action(command)

    def _hide(self, *_):
        if self.indicator:
            self.window.hide(); return True
        self.quit(); return True

    def _action(self, command):
        if hasattr(self, "effects"): self.effects.command(command)

    def quit(self):
        if hasattr(self, "effects"): self.effects.shutdown()
        if self.indicator: self.indicator.set_status(self.Indicator.IndicatorStatus.PASSIVE)
        Gtk.main_quit()

    def _button(self, _, label):
        if label == "Copy":
            buffer = self.output.get_buffer(); start, end = buffer.get_bounds()
            text = buffer.get_text(start, end, True)
            success = bool(getattr(self, "effects", None) and
                           self.effects.clipboard.copy_text(text, self.effects.x11))
            self.status.set_text("Text copied" if success else "Copy could not be confirmed")
        elif label == "Check server": self.effects.health()
        elif label == "Settings": self.settings_dialog()
        elif label == "Quit": self.quit()
        else: self._action(label.lower())

    def settings_dialog(self):
        dialog = Gtk.Dialog(title="Settings", transient_for=self.window, flags=0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL); dialog.add_button("Save", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        shortcut_state = Gtk.Label(label=self.effects.shortcut_status)
        url = Gtk.Entry(); url.set_text(self.effects.config.base_url)
        timeout = Gtk.SpinButton.new_with_range(1, 3600, 1); timeout.set_value(self.effects.config.timeout_seconds)
        source = Gtk.Entry(); source.set_text(self.effects.config.audio_source)
        key = Gtk.Entry(); key.set_visibility(False); key.set_placeholder_text("Leave blank to keep existing key")
        auto = Gtk.CheckButton(label="Insert automatically only into original active X11 window")
        auto.set_active(self.effects.config.auto_insert)
        hotkey_enabled = Gtk.CheckButton(label="Enable global X11 shortcut")
        hotkey_enabled.set_active(self.effects.config.hotkey_enabled)
        hotkey = Gtk.Entry(); hotkey.set_text(self.effects.config.hotkey_accelerator)
        for row, (label, widget) in enumerate((("Shortcut status", shortcut_state), ("API base URL", url), ("Timeout (seconds)", timeout), ("Audio source", source), ("API key", key), ("", auto), ("", hotkey_enabled), ("Shortcut (e.g. Ctrl+Space)", hotkey))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1); grid.attach(widget, 1, row, 1, 1)
        dialog.get_content_area().add(grid); dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            try: self.effects.save_settings(url.get_text(), timeout.get_value_as_int(), source.get_text(), key.get_text(), auto.get_active(), hotkey_enabled.get_active(), hotkey.get_text())
            except (ValueError, PermissionError, OSError, RuntimeError): self.status.set_text("Settings rejected; shortcut may be unavailable or config permissions invalid")
        dialog.destroy()


def launch_window():
    from .desktop import DesktopController
    window = DesktopWindow(); DesktopController(window); Gtk.main(); return window
