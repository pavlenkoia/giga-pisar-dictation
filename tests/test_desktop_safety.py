import ctypes
import ctypes.util
import unittest
from giga_pisar_dictation.clipboard import GtkClipboardAdapter
from giga_pisar_dictation.x11 import X11Adapter, XModifierKeymap, XWindowAttributes


class FakeClipboard:
    def __init__(self, text): self.text = text; self.listeners = []; self.owner = 1; self.targets = [] if text is None else ["text/plain"]
    def connect(self, signal, callback): self.listeners.append(callback)
    def wait_for_text(self): return self.text
    def wait_for_targets(self): return True, self.targets
    def set_text(self, text, length):
        self.text = text; self.owner = (self.owner or 0) + 1
        for callback in self.listeners: callback(self, None)


class FakeX11:
    def __init__(self, allow, clipboard, before_return=None, owner_query_hook=None):
        self.allow = allow; self.before_return = before_return; self.clipboard = clipboard
        self.owner_query_hook = owner_query_hook; self.owner_queries = 0
    def paste(self, target, modifiers):
        if self.before_return: self.before_return()
        return self.allow
    def clipboard_owner(self):
        self.owner_queries += 1
        if self.owner_query_hook: self.owner_query_hook(self.owner_queries)
        return self.clipboard.owner


class FakeTimers:
    def __init__(self): self.callbacks = {}; self.cancelled = []
    def schedule(self, delay, callback): self.callbacks[7] = callback; return 7
    def cancel(self, source_id): self.cancelled.append(source_id)


class SafetyTests(unittest.TestCase):
    def test_ctypes_signatures_use_pointer_sized_display_and_full_attributes(self):
        self.assertGreaterEqual(XWindowAttributes.root.size, 8)
        self.assertEqual(XWindowAttributes.screen.offset + XWindowAttributes.screen.size, ctypes.sizeof(XWindowAttributes))
        adapter = X11Adapter.__new__(X11Adapter)
        adapter.x = ctypes.CDLL(ctypes.util.find_library("X11")); adapter.xt = ctypes.CDLL(ctypes.util.find_library("Xtst"))
        adapter._set_signatures()
        self.assertEqual(adapter.x.XOpenDisplay.restype, ctypes.c_void_p)
        self.assertEqual(adapter.x.XGetWindowAttributes.argtypes[-1], ctypes.POINTER(XWindowAttributes))
        self.assertEqual(adapter.x.XGetSelectionOwner.restype, ctypes.c_ulong)
        self.assertEqual(adapter.xt.XTestFakeKeyEvent.argtypes[0], ctypes.c_void_p)
        self.assertEqual(adapter.x.XGetModifierMapping.restype, ctypes.POINTER(XModifierKeymap))
        closed = X11Adapter.__new__(X11Adapter); closed.x = type("X", (), {})()
        self.assertFalse(X11Adapter.window_exists(closed, 0))

    def test_focus_change_closed_window_and_modifiers_prevent_keys(self):
        adapter = X11Adapter.__new__(X11Adapter)
        adapter.active_window = lambda: 12; adapter.window_exists = lambda window: True
        adapter._modifier_keycodes = lambda: {37}; adapter._query_keymap = lambda: bytes(32)
        adapter.xt = type("XT", (), {"XTestFakeKeyEvent": lambda *args: self.fail("must not synthesize keys")})()
        adapter.display = 0
        adapter.x = type("X", (), {"XKeysymToKeycode": staticmethod(lambda _display, sym: 37 if sym == 0xFFE3 else 55)})()
        self.assertFalse(adapter.paste(11))
        adapter.window_exists = lambda window: False; self.assertFalse(adapter.paste(12))
        adapter.window_exists = lambda window: True
        held = bytearray(32); held[91 >> 3] |= 1 << (91 & 7)
        adapter._modifier_keycodes = lambda: {91}; adapter._query_keymap = lambda: bytes(held)
        self.assertFalse(adapter.paste(12))

    def test_nontext_clipboard_and_changed_ownership_are_not_destroyed(self):
        nontext = FakeClipboard(None); adapter = GtkClipboardAdapter(nontext)
        self.assertFalse(adapter.paste_safely("dictated", FakeX11(True, nontext), 1))
        self.assertIsNone(nontext.text)
        clipboard = FakeClipboard("old text"); adapter = GtkClipboardAdapter(clipboard)
        x11 = FakeX11(False, clipboard, lambda: clipboard.set_text("new user data", -1))
        self.assertFalse(adapter.paste_safely("dictated", x11, 1))
        self.assertEqual(clipboard.text, "new user data")

    def test_refusal_restores_previous_text_only_while_x_selection_owner_unchanged(self):
        clipboard = FakeClipboard("old text"); adapter = GtkClipboardAdapter(clipboard)
        self.assertFalse(adapter.paste_safely("dictated", FakeX11(False, clipboard), 1))
        self.assertEqual(clipboard.text, "old text")

    def test_successful_delayed_restore_and_shutdown_restore_only_with_ownership_proof(self):
        clipboard = FakeClipboard("old text"); timers = FakeTimers()
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard)
        self.assertTrue(adapter.paste_safely("dictated", x11, 1))
        self.assertEqual(clipboard.text, "dictated")
        self.assertFalse(timers.callbacks[7]())
        self.assertEqual(clipboard.text, "old text")
        self.assertEqual(adapter._restore_sources, {})

        clipboard = FakeClipboard("old text"); timers = FakeTimers()
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard)
        self.assertTrue(adapter.paste_safely("dictated", x11, 1))
        adapter.shutdown()
        self.assertEqual(clipboard.text, "old text")
        self.assertEqual(timers.cancelled, [7])

        clipboard = FakeClipboard("old text"); timers = FakeTimers()
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard)
        self.assertTrue(adapter.paste_safely("dictated", x11, 1))
        clipboard.set_text("new user data", -1)
        adapter.shutdown()
        self.assertEqual(clipboard.text, "new user data")
        self.assertEqual(timers.cancelled, [7])

    def test_modifier_mapping_includes_altgr_and_custom_modifier_keycodes(self):
        adapter = X11Adapter.__new__(X11Adapter)
        values = (ctypes.c_ubyte * 24)(0, 0, 91, 108, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        mapping = XModifierKeymap(3, values)
        adapter.display = 0
        adapter.x = type("X", (), {"XGetModifierMapping": staticmethod(lambda _display: ctypes.pointer(mapping)),
                                    "XFreeModifiermap": staticmethod(lambda _mapping: 1)})()
        self.assertEqual(adapter._modifier_keycodes(), {91, 108})
        keymap = bytearray(32)
        for code in (108, 91):
            keymap[code >> 3] |= 1 << (code & 7)
            self.assertTrue(adapter.modifiers_down(bytes(keymap), {91, 108}))
            keymap[code >> 3] &= ~(1 << (code & 7))
        self.assertFalse(adapter.modifiers_down(bytes(keymap), {91, 108}))

    def test_paste_refuses_held_altgr_custom_modifier_or_v_and_releases_only_pressed_keys(self):
        def make_adapter(held=(), fail_down=None):
            adapter = X11Adapter.__new__(X11Adapter)
            state = bytearray(32)
            for code in held: state[code >> 3] |= 1 << (code & 7)
            adapter.display = 0
            adapter._query_keymap = lambda: bytes(state)
            adapter._modifier_keycodes = lambda: {37, 91, 108}
            adapter.active_window = lambda: 42; adapter.window_exists = lambda _window: True
            adapter.x = type("X", (), {"XKeysymToKeycode": staticmethod(lambda _display, sym: 37 if sym == 0xFFE3 else 55),
                                        "XFlush": staticmethod(lambda _display: 1)})()
            adapter.events = []
            def fake(_display, code, down, _delay):
                adapter.events.append((code, down))
                if down and code == fail_down: return 0
                if down: state[code >> 3] |= 1 << (code & 7)
                else: state[code >> 3] &= ~(1 << (code & 7))
                return 1
            adapter.xt = type("XT", (), {"XTestFakeKeyEvent": staticmethod(fake)})()
            return adapter
        for held in ((108,), (91,), (55,), (37,)):
            adapter = make_adapter(held)
            self.assertFalse(adapter.paste(42))
            self.assertEqual(adapter.events, [])
        adapter = make_adapter(fail_down=55)
        self.assertFalse(adapter.paste(42))
        self.assertEqual(adapter.events, [(37, 1), (55, 1), (37, 0)])
        adapter = make_adapter()
        self.assertTrue(adapter.paste(42))
        self.assertEqual(adapter.events, [(37, 1), (55, 1), (55, 0), (37, 0)])

    def test_explicit_copy_overwrites_empty_text_nontext_and_unknown_clipboards(self):
        for clipboard in (FakeClipboard(None), FakeClipboard("previous")):
            self.assertTrue(GtkClipboardAdapter(clipboard).copy_text("copied"))
            self.assertEqual(clipboard.text, "copied")

        nontext = FakeClipboard(None); nontext.targets = ["image/png"]
        self.assertTrue(GtkClipboardAdapter(nontext).copy_text("copied"))
        self.assertEqual(nontext.text, "copied")

        unknown = FakeClipboard(None); unknown.wait_for_targets = lambda: (False, None)
        self.assertTrue(GtkClipboardAdapter(unknown).copy_text("copied"))
        self.assertEqual(unknown.text, "copied")

    def test_explicit_copy_rejects_empty_or_missing_result_without_writing(self):
        for result in (None, ""):
            clipboard = FakeClipboard("keep me")
            self.assertFalse(GtkClipboardAdapter(clipboard).copy_text(result))
            self.assertEqual(clipboard.text, "keep me")

    def test_explicit_copy_reports_write_and_readback_failures(self):
        failed_write = FakeClipboard("previous")
        failed_write.set_text = lambda text, length: (_ for _ in ()).throw(OSError("write failed"))
        self.assertFalse(GtkClipboardAdapter(failed_write).copy_text("copied"))
        self.assertEqual(failed_write.text, "previous")

        failed_readback = FakeClipboard("previous")
        def write_without_readback(text, length): failed_readback.text = text
        failed_readback.set_text = write_without_readback
        failed_readback.wait_for_text = lambda: "different"
        self.assertFalse(GtkClipboardAdapter(failed_readback).copy_text("copied"))
        self.assertEqual(failed_readback.text, "copied")

    def test_copy_button_uses_full_output_without_selection(self):
        from giga_pisar_dictation.gui import DesktopWindow
        class Buffer:
            def get_bounds(self): return "start", "end"
            def get_text(self, start, end, include_hidden):
                self.asserted = (start, end, include_hidden)
                return "complete output"
        class Output:
            def get_buffer(self): return buffer
        class Status:
            def set_text(self, value): self.value = value
        class Clipboard:
            def copy_text(self, text, x11): self.copied = (text, x11); return True
        window = DesktopWindow.__new__(DesktopWindow)
        buffer = Buffer(); window.output = Output(); window.status = Status()
        clipboard = Clipboard(); window.effects = type("Effects", (), {"clipboard": clipboard, "x11": None})()
        DesktopWindow._button(window, None, "copy")
        self.assertEqual(clipboard.copied, ("complete output", None))
        self.assertEqual(window.status.value, "Текст скопирован")

    def test_manual_copy_cancels_pending_autopaste_restore(self):
        clipboard = FakeClipboard("old text"); timers = FakeTimers()
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        self.assertTrue(adapter.paste_safely("auto text", FakeX11(True, clipboard), 1))
        self.assertTrue(adapter.copy_text("manual text", FakeX11(True, clipboard)))
        self.assertEqual(timers.cancelled, [7])
        timers.callbacks[7]()
        self.assertEqual(clipboard.text, "manual text")


if __name__ == "__main__": unittest.main()
