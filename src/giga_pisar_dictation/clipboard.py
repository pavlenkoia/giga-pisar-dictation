"""Clipboard adapter for explicit copies and best-effort-restoring X11 paste."""


class ClipboardSafety:
    @staticmethod
    def text_or_none(value):
        return value if isinstance(value, str) else None


class GtkClipboardAdapter:
    PREPARATION_TIMEOUT_MS = 200
    CONFIRMATION_TIMEOUT_MS = 200
    RESTORE_DELAY_MS = 300

    def __init__(self, clipboard=None, scheduler=None, cancel_timer=None):
        if clipboard is None:
            import gi
            gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
            from gi.repository import Gtk, Gdk
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.clipboard = clipboard
        self._scheduler, self._cancel_timer = scheduler, cancel_timer
        self._owner_generation = 0
        self._paste_generation = 0
        self._paste = None
        if hasattr(clipboard, "connect"):
            clipboard.connect("owner-change", self._owner_changed)

    def _owner_changed(self, *_):
        self._owner_generation += 1

    def get_text(self):
        return ClipboardSafety.text_or_none(self.clipboard.wait_for_text())

    def set_text(self, text):
        self.clipboard.set_text(text, -1)

    def copy_text(self, text, x11=None):
        """Explicitly replace clipboard with non-empty recognized text."""
        if not isinstance(text, str) or not text:
            return False
        self.cancel_pending_paste(restore=False)
        try:
            self.set_text(text)
            return self.get_text() == text
        except Exception:
            return False

    def _schedule(self, callback, delay):
        if self._scheduler:
            return self._scheduler(delay, callback)
        from gi.repository import GLib
        return GLib.timeout_add(delay, callback)

    def _cancel_timer_source(self, source):
        if self._cancel_timer:
            self._cancel_timer(source)
        else:
            from gi.repository import GLib
            GLib.source_remove(source)

    @staticmethod
    def _notify(callback, sent, reason):
        try:
            callback(sent, reason)
        except Exception:
            pass

    def _current(self, operation):
        return self._paste is operation and operation["token"] == self._paste_generation

    def _arm_timeout(self, operation, phase, delay):
        try:
            operation["timer"] = self._schedule(lambda: self._phase_timeout(operation, phase), delay)
        except Exception:
            operation["timer"] = None
            return False
        return True

    def _cancel_operation_timer(self, operation):
        source, operation["timer"] = operation["timer"], None
        if source is not None:
            try:
                self._cancel_timer_source(source)
            except Exception:
                pass

    def _phase_timeout(self, operation, phase):
        if not self._current(operation) or operation["phase"] != phase:
            return False
        operation["timer"] = None
        if phase == "snapshot-text":
            self._request_image(operation)
        elif phase == "snapshot-image":
            self._install_and_paste(operation)
        elif phase == "confirmation":
            self._finish(operation, False, "Не удалось подтвердить установленный текст в буфере обмена")
        elif phase == "restore-delay":
            self._finish(operation, True, None)
        return False

    def _request_snapshot(self, operation):
        if not self._current(operation):
            return
        operation["phase"] = "snapshot-text"
        if not self._arm_timeout(operation, "snapshot-text", self.PREPARATION_TIMEOUT_MS):
            self._install_and_paste(operation)
            return
        try:
            if not self._current(operation):
                return
            self.clipboard.request_text(self._snapshot_text, operation)
        except Exception:
            if self._current(operation) and operation["phase"] == "snapshot-text":
                self._cancel_operation_timer(operation)
                self._request_image(operation)

    def _snapshot_text(self, _clipboard, text, operation):
        if not self._current(operation) or operation["phase"] != "snapshot-text":
            return
        if self._owner_generation != operation["initial_owner"]:
            self._finish(operation, False, "Буфер обмена изменился")
            return
        self._cancel_operation_timer(operation)
        if isinstance(text, str) and text:
            operation["snapshot"] = ("text", text)
            self._install_and_paste(operation)
        else:
            self._request_image(operation)

    def _request_image(self, operation):
        if not self._current(operation):
            return
        operation["phase"] = "snapshot-image"
        if not self._arm_timeout(operation, "snapshot-image", self.PREPARATION_TIMEOUT_MS):
            self._install_and_paste(operation)
            return
        try:
            if not self._current(operation):
                return
            self.clipboard.request_image(self._snapshot_image, operation)
        except Exception:
            if self._current(operation) and operation["phase"] == "snapshot-image":
                self._cancel_operation_timer(operation)
                self._install_and_paste(operation)

    def _snapshot_image(self, _clipboard, image, operation):
        if not self._current(operation) or operation["phase"] != "snapshot-image":
            return
        if self._owner_generation != operation["initial_owner"]:
            self._finish(operation, False, "Буфер обмена изменился")
            return
        self._cancel_operation_timer(operation)
        if image is not None:
            operation["snapshot"] = ("image", image)
        self._install_and_paste(operation)

    def _install_and_paste(self, operation):
        if not self._current(operation):
            return
        if self._owner_generation != operation["initial_owner"]:
            self._finish(operation, False, "Буфер обмена изменился")
            return
        self._cancel_operation_timer(operation)
        operation["phase"] = "installing"
        try:
            self.set_text(operation["text"])
            if not self._current(operation):
                return
            owner = operation["x11"].clipboard_owner()
            if not self._current(operation):
                return
            if not owner:
                self._finish(operation, False, "Не удалось подтвердить установленный текст в буфере обмена")
                return
            operation["installed_owner"] = owner
            operation["installed"] = True
            operation["phase"] = "confirmation"
            if not self._arm_timeout(operation, "confirmation", self.CONFIRMATION_TIMEOUT_MS):
                self._finish(operation, False, "Не удалось подтвердить установленный текст в буфере обмена")
                return
            if not self._current(operation):
                return
            self.clipboard.request_text(self._confirmed_text, operation)
        except Exception:
            if self._current(operation):
                self._finish(operation, False, "Не удалось безопасно выполнить автоматическую вставку")

    def _confirmed_text(self, _clipboard, text, operation):
        if not self._current(operation) or operation["phase"] != "confirmation":
            return
        if text != operation["text"]:
            self._finish(operation, False, "Не удалось подтвердить установленный текст в буфере обмена")
            return
        try:
            owner = operation["x11"].clipboard_owner()
        except Exception:
            self._finish(operation, False, "Не удалось подтвердить установленный текст в буфере обмена")
            return
        if not self._current(operation):
            return
        if owner != operation["installed_owner"]:
            self._finish(operation, False, "Владелец буфера обмена изменился")
            return
        self._cancel_operation_timer(operation)
        try:
            modifiers = operation["modifiers"]
            if callable(modifiers):
                modifiers = modifiers()
            if not self._current(operation):
                return
            x11 = operation["x11"]
            owner = x11.clipboard_owner()
            if not self._current(operation):
                return
            if owner != operation["installed_owner"]:
                self._finish(operation, False, "Владелец буфера обмена изменился")
                return
            if hasattr(x11, "paste_with_reason"):
                sent, reason = x11.paste_with_reason(operation["window"], modifiers)
            else:
                sent = x11.paste(operation["window"], modifiers)
                reason = None if sent else "Исходное окно изменилось или X11 отказал во вставке"
        except Exception:
            sent, reason = False, "Не удалось безопасно выполнить автоматическую вставку"
        if not self._current(operation):
            return
        if not sent:
            self._finish(operation, False, reason)
            return
        operation["phase"] = "restore-delay"
        if not self._arm_timeout(operation, "restore-delay", self.RESTORE_DELAY_MS):
            self._finish(operation, True, None)


    def _restore(self, operation):
        if not operation["installed"]:
            return
        try:
            if not self._restore_current(operation):
                return
            owner = operation["x11"].clipboard_owner()
            if not self._restore_current(operation) or owner != operation["installed_owner"]:
                return
            if not self._restore_current(operation):
                return
            self.clipboard.request_text(self._restore_text, (operation, owner))
        except Exception:
            pass

    def _restore_current(self, operation):
        return (operation["token"] == self._paste_generation or
                operation.get("restore_token") == self._paste_generation)

    def _restore_text(self, _clipboard, text, data):
        operation, owner = data
        if not self._restore_current(operation) or text != operation["text"]:
            return
        try:
            current_owner = operation["x11"].clipboard_owner()
        except Exception:
            return
        if (not self._restore_current(operation) or current_owner != owner or
                current_owner != operation["installed_owner"]):
            return
        try:
            if not self._restore_current(operation):
                return
            snapshot = operation["snapshot"]
            if snapshot is None:
                self.clipboard.clear()
            elif snapshot[0] == "text":
                self.set_text(snapshot[1])
            else:
                self.clipboard.set_image(snapshot[1])
        except Exception:
            pass

    def _finish(self, operation, sent, reason):
        if not self._current(operation):
            return
        self._paste = None
        self._cancel_operation_timer(operation)
        self._restore(operation)
        self._notify(operation["callback"], sent, reason)

    def cancel_pending_paste(self, restore=True):
        self._paste_generation += 1
        operation, self._paste = self._paste, None
        if operation is None:
            return
        self._cancel_operation_timer(operation)
        if restore:
            operation["restore_token"] = self._paste_generation
            self._restore(operation)

    def paste_safely_async(self, text, x11, target_window, modifiers_down, callback):
        """Snapshot text/image asynchronously, paste once, then best-effort restore."""
        self.cancel_pending_paste()
        token = self._paste_generation
        if not isinstance(text, str) or not text:
            self._notify(callback, False, "Нет текста для вставки")
            return
        operation = {"token": token, "text": text, "x11": x11, "window": target_window,
                     "modifiers": modifiers_down, "callback": callback, "snapshot": None,
                     "initial_owner": self._owner_generation, "installed": False,
                     "installed_owner": None, "timer": None, "phase": None}
        self._paste = operation
        self._request_snapshot(operation)

    def shutdown(self):
        self.cancel_pending_paste()
