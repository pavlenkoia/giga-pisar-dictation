"""Session tray-host policy; unknown host availability must never hide the window."""


def requires_quit_confirmation(state):
    return getattr(state, "name", "") in {"RECORDING", "FINALIZING", "REQUESTING"}


def icon_for_state(state):
    name = getattr(state, "name", "")
    return {"RECORDING": "giga-pisar-dictation-recording",
            "FINALIZING": "giga-pisar-dictation-processing",
            "REQUESTING": "giga-pisar-dictation-processing",
            "ERROR": "giga-pisar-dictation-error"}.get(name, "giga-pisar-dictation-idle")


class TrayWatcher:
    """Observe the session StatusNotifierWatcher without assuming indicator creation means readiness."""
    BUS_NAME = "org.kde.StatusNotifierWatcher"
    OBJECT_PATH = "/StatusNotifierWatcher"
    INTERFACE = "org.kde.StatusNotifierWatcher"

    def __init__(self, callback, gio=None):
        if gio is None:
            from gi.repository import Gio, GLib
            gio = Gio
        else:
            from gi.repository import GLib
        self.Gio = gio
        self.GLib = GLib
        self.callback = callback
        self.connection = gio.bus_get_sync(gio.BusType.SESSION, None)
        self.signal_id = self.connection.signal_subscribe(
            self.BUS_NAME, self.INTERFACE, None, self.OBJECT_PATH, None,
            gio.DBusSignalFlags.NONE, self._signal)
        self.watch_id = gio.bus_watch_name(gio.BusType.SESSION, self.BUS_NAME,
                                           gio.BusNameWatcherFlags.NONE, self._appeared, self._vanished)

    def _query(self):
        try:
            reply = self.connection.call_sync(
                self.BUS_NAME, self.OBJECT_PATH, "org.freedesktop.DBus.Properties", "Get",
                self.GLib.Variant("(ss)", (self.INTERFACE, "IsStatusNotifierHostRegistered")),
                self.GLib.VariantType.new("(v)"), self.Gio.DBusCallFlags.NONE, 1000, None)
            self.callback(bool(reply.unpack()[0]))
        except Exception:
            self.callback(False)

    def _appeared(self, *_): self._query()
    def _vanished(self, *_): self.callback(False)
    def _signal(self, *_): self._query()

    def close(self):
        self.Gio.bus_unwatch_name(self.watch_id)
        self.connection.signal_unsubscribe(self.signal_id)


class TrayPolicy:
    def __init__(self, available=None):
        self.available = available
        self.listeners = []

    @property
    def ready(self):
        return self.available is True

    def update(self, available):
        changed = self.available != available
        self.available = available
        if changed:
            for listener in tuple(self.listeners):
                listener(available)

    def subscribe(self, listener):
        self.listeners.append(listener)

    def close(self):
        self.listeners.clear()

    def may_hide(self):
        return self.ready

    def may_start_hidden(self):
        return self.ready
