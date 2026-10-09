"""Clipboard adapter with bounded proof of newly installed text ownership."""

class ClipboardSafety:
    @staticmethod
    def text_or_none(value):
        return value if isinstance(value, str) else None


class GtkClipboardAdapter:
    def __init__(self, clipboard=None, pump=None, scheduler=None, cancel_timer=None, clock=None):
        if clipboard is None:
            import gi
            gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
            from gi.repository import Gtk, Gdk
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            pump = lambda: Gtk.main_iteration_do(False)
        self.clipboard = clipboard
        self._pump, self._scheduler, self._cancel_timer = pump, scheduler, cancel_timer
        if clock is None:
            import time
            clock = time.monotonic
        self._clock = clock
        self._owner_generation = 0
        self._pending_pastes = {}
        self._paste_generation = 0
        if hasattr(clipboard, "connect"):
            clipboard.connect("owner-change", self._owner_changed)

    def _owner_changed(self, *_):
        self._owner_generation += 1
        for token in tuple(self._pending_pastes):
            self._complete_pending(token)

    def cancel_pending_paste(self):
        self._paste_generation += 1
        for token in tuple(self._pending_pastes):
            self._finish_pending(token)

    def get_text(self): return ClipboardSafety.text_or_none(self.clipboard.wait_for_text())
    def set_text(self, text): self.clipboard.set_text(text, -1)

    def copy_text(self, text, x11=None):
        """Explicitly replace clipboard with non-empty recognized text."""
        if not isinstance(text, str) or not text: return False
        self.cancel_pending_paste()
        try:
            self.set_text(text)
            return self.get_text() == text
        except Exception:
            return False

    def _set_owned_text(self, text, x11):
        before = self._owner_generation
        self.set_text(text)
        if self._pump: self._pump()
        owner = x11.clipboard_owner()
        generation = self._owner_generation
        if generation <= before or not owner: return None, None
        current = self.get_text()
        if current != text or self._owner_generation != generation: return None, None
        current_owner = x11.clipboard_owner()
        if self._owner_generation != generation or current_owner != owner: return None, None
        return generation, owner

    def _still_owned(self, x11, generation, owner):
        if generation is None or self._owner_generation != generation: return False
        current_owner = x11.clipboard_owner()
        return self._owner_generation == generation and current_owner == owner

    def _schedule(self, callback, delay=200):
        if self._scheduler: return self._scheduler(delay, callback)
        from gi.repository import GLib
        return GLib.timeout_add(delay, callback)

    def _cancel(self, source_id):
        if self._cancel_timer: self._cancel_timer(source_id)
        else:
            from gi.repository import GLib
            GLib.source_remove(source_id)

    def paste_safely(self, text, x11, target_window, modifiers_down=False):
        return self.paste_safely_with_reason(text, x11, target_window, modifiers_down)[0]

    def paste_safely_with_reason(self, text, x11, target_window, modifiers_down=False):
        try:
            if not isinstance(text, str) or not text: return False, "Нет текста для вставки"
            generation, owner = self._set_owned_text(text, x11)
            if generation is None: return False, "Не удалось подтвердить установленный текст в буфере обмена"
            if not self._still_owned(x11, generation, owner):
                return False, "Владелец буфера обмена изменился"
            if hasattr(x11, "paste_with_reason"):
                return x11.paste_with_reason(target_window, modifiers_down)
            sent = x11.paste(target_window, modifiers_down)
            return sent, None if sent else "Исходное окно изменилось или X11 отказал во вставке"
        except Exception:
            return False, "Не удалось безопасно выполнить автоматическую вставку"

    def paste_safely_async(self, text, x11, target_window, modifiers_down, callback):
        """Wait at most 200ms for proof of this operation's clipboard text and owner."""
        self.cancel_pending_paste()
        token = self._paste_generation
        if not isinstance(text, str) or not text:
            callback(False, "Нет текста для вставки"); return
        before = self._owner_generation
        deadline = self._clock() + 0.2
        try:
            self.set_text(text)
            if token != self._paste_generation: return
            expected_owner = x11.clipboard_owner()
            if token != self._paste_generation:
                return
        except Exception:
            if token == self._paste_generation: callback(False, "Не удалось безопасно выполнить автоматическую вставку")
            return
        pending = {"generation": token, "before": before, "owner": expected_owner,
                   "deadline": deadline, "text": text, "x11": x11, "window": target_window,
                   "modifiers": modifiers_down, "callback": callback, "source": None,
                   "checking": False}
        self._pending_pastes[token] = pending
        try:
            delay = max(0, int((deadline - self._clock()) * 1000 + .999999))
            source = self._schedule(lambda: self._timeout_pending(token), delay)
        except Exception:
            self._finish_pending(token)
            self._notify(callback, False, "Не удалось безопасно выполнить автоматическую вставку"); return
        if not self._pending_is_current(token, pending):
            try: self._cancel(source)
            except Exception: pass
            return
        pending["source"] = source
        self._complete_pending(token)

    @staticmethod
    def _notify(callback, sent, reason):
        try: callback(sent, reason)
        except Exception: pass

    def _pending_is_current(self, token, pending):
        return self._pending_pastes.get(token) is pending and token == self._paste_generation

    def _finish_pending(self, token):
        pending = self._pending_pastes.pop(token, None)
        if pending and pending["source"] is not None:
            try: self._cancel(pending["source"])
            except Exception: pass

    def _timeout_pending(self, token):
        pending = self._pending_pastes.get(token)
        if pending is not None:
            self._finish_pending(token)
            self._notify(pending["callback"], False, "Не удалось подтвердить установленный текст в буфере обмена")
        return False

    def _complete_pending(self, token):
        pending = self._pending_pastes.get(token)
        if (pending is None or pending["checking"] or not self._pending_is_current(token, pending)): return False
        pending["checking"] = True
        try:
            if self._clock() >= pending["deadline"]: return self._timeout_pending(token)
            x11 = pending["x11"]
            owner = x11.clipboard_owner()
            if not self._pending_is_current(token, pending): return False
            generation = self._owner_generation
            if generation <= pending["before"]:
                pending["checking"] = False; return True
            text = self.get_text()
            if not self._pending_is_current(token, pending): return False
            if self._owner_generation != generation or not owner or owner != pending["owner"] or text != pending["text"]:
                self._refuse_pending(token, pending, "Владелец или содержимое буфера обмена изменилось"); return False
            current_owner = x11.clipboard_owner()
            if not self._pending_is_current(token, pending): return False
            if self._owner_generation != generation or current_owner != owner:
                self._refuse_pending(token, pending, "Владелец буфера обмена изменился"); return False
            modifiers = pending["modifiers"]()
            if not self._pending_is_current(token, pending): return False
            if self._owner_generation != generation:
                self._refuse_pending(token, pending, "Владелец буфера обмена изменился"); return False
            final_owner = x11.clipboard_owner()
            if not self._pending_is_current(token, pending): return False
            if self._owner_generation != generation or final_owner != owner:
                self._refuse_pending(token, pending, "Владелец буфера обмена изменился"); return False
            final_text = self.get_text()
            if not self._pending_is_current(token, pending): return False
            if self._owner_generation != generation or final_text != pending["text"]:
                self._refuse_pending(token, pending, "Владелец или содержимое буфера обмена изменилось"); return False
            final_owner_after_read = x11.clipboard_owner()
            if not self._pending_is_current(token, pending): return False
            if self._owner_generation != generation or final_owner_after_read != owner:
                self._refuse_pending(token, pending, "Владелец буфера обмена изменился"); return False
            if self._clock() >= pending["deadline"]: return self._timeout_pending(token)
            if not self._pending_is_current(token, pending): return False
            self._finish_pending(token)
            if hasattr(x11, "paste_with_reason"):
                sent, reason = x11.paste_with_reason(pending["window"], modifiers)
            else:
                sent = x11.paste(pending["window"], modifiers); reason = None
            self._notify(pending["callback"], sent, reason if not sent else None)
            return False
        except Exception:
            # XTest runs after pending removal; token identity still distinguishes cancellation/new work.
            current = token == self._paste_generation
            self._finish_pending(token)
            if current: self._notify(pending["callback"], False, "Не удалось безопасно выполнить автоматическую вставку")
            return False

    def _refuse_pending(self, token, pending, reason):
        # A nested operation owns completion once identity/generation has changed.
        if not self._pending_is_current(token, pending): return False
        self._finish_pending(token)
        self._notify(pending["callback"], False, reason)
        return True

    def shutdown(self):
        self.cancel_pending_paste()
