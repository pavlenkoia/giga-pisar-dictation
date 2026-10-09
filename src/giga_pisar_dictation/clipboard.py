"""Clipboard adapter with X selection owner proof and change generations."""

class ClipboardSafety:
    @staticmethod
    def text_or_none(value):
        return value if isinstance(value, str) else None


class GtkClipboardAdapter:
    def __init__(self, clipboard=None, pump=None, scheduler=None, cancel_timer=None):
        if clipboard is None:
            import gi
            gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
            from gi.repository import Gtk, Gdk
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            pump = lambda: Gtk.main_iteration_do(False)
        self.clipboard = clipboard
        self._pump = pump
        self._scheduler = scheduler
        self._cancel_timer = cancel_timer
        self._owner_generation = 0
        self._restore_sources = {}
        if hasattr(clipboard, "connect"): clipboard.connect("owner-change", self._owner_changed)

    def _owner_changed(self, *_): self._owner_generation += 1
    def get_text(self): return ClipboardSafety.text_or_none(self.clipboard.wait_for_text())
    def set_text(self, text): self.clipboard.set_text(text, -1)

    def copy_text(self, text, x11=None):
        """Explicitly replace clipboard contents with non-empty recognized text."""
        if not isinstance(text, str) or not text:
            return False
        for source_id in tuple(self._restore_sources):
            try:
                self._cancel(source_id)
            except Exception:
                return False
            self._restore_sources.pop(source_id, None)
        try:
            self.set_text(text)
            return self.get_text() == text
        except Exception:
            return False

    def _set_owned_text(self, text, x11, restore_if_unobserved=None):
        before = self._owner_generation
        self.set_text(text)
        if self._pump: self._pump()
        owner = x11.clipboard_owner()
        generation = self._owner_generation if self._owner_generation > before else None
        if not owner or self.get_text() != text: return None, None
        if generation is None:
            if x11.clipboard_owner() == owner and self.get_text() == text and restore_if_unobserved is not None:
                self.set_text(restore_if_unobserved)
            return None, None
        return generation, owner

    def _still_owned(self, x11, generation, owner):
        return (generation is not None and self._owner_generation == generation and
                x11.clipboard_owner() == owner)

    def _schedule(self, callback):
        if self._scheduler: return self._scheduler(1200, callback)
        from gi.repository import GLib
        return GLib.timeout_add(1200, callback)

    def _cancel(self, source_id):
        if self._cancel_timer: self._cancel_timer(source_id)
        else:
            from gi.repository import GLib
            GLib.source_remove(source_id)

    def paste_safely(self, text, x11, target_window, modifiers_down=False):
        previous = self.get_text()
        if previous is None: return False
        generation, owner = self._set_owned_text(text, x11, previous)
        if not self._still_owned(x11, generation, owner): return False
        if not x11.paste(target_window, modifiers_down):
            if self._still_owned(x11, generation, owner): self._set_owned_text(previous, x11)
            return False
        source_id = None
        token = (previous, text, generation, owner, x11)
        def restore():
            self._restore_sources.pop(source_id, None)
            self._restore_if_owned(token)
            return False
        source_id = self._schedule(restore)
        self._restore_sources[source_id] = token
        return True

    def _restore_if_owned(self, token):
        previous, text, generation, owner, x11 = token
        if self._still_owned(x11, generation, owner) and self.get_text() == text:
            self._set_owned_text(previous, x11)
            return True
        return False

    def shutdown(self):
        # Restore first while the X display is still open; cancel every delayed callback afterwards.
        for source_id, token in tuple(self._restore_sources.items()):
            self._restore_if_owned(token)
            self._cancel(source_id)
        self._restore_sources.clear()
