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
        self.owner_query_hook = owner_query_hook; self.owner_queries = 0; self.paste_calls = []
    def paste(self, target, modifiers):
        self.paste_calls.append((target, modifiers))
        if self.before_return: self.before_return()
        return self.allow
    def clipboard_owner(self):
        self.owner_queries += 1
        if self.owner_query_hook: self.owner_query_hook(self.owner_queries)
        return self.clipboard.owner


class FakeTimers:
    def __init__(self, fail_on_call=None):
        self.callbacks = {}; self.cancelled = []; self.delays = []; self.next_id = 7
        self.calls = 0; self.fail_on_call = fail_on_call
    def schedule(self, delay, callback):
        self.calls += 1
        if self.calls == self.fail_on_call: raise RuntimeError("scheduler failure")
        source_id = self.next_id; self.next_id += 1
        self.delays.append(delay); self.callbacks[source_id] = callback; return source_id
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

    def _diagnostic_x11(self):
        adapter = X11Adapter.__new__(X11Adapter)
        state = bytearray(32)
        adapter.display = 0
        adapter.query_count = 0
        adapter.mapping_count = 0
        adapter.events = []
        adapter.active_window = lambda: 42
        adapter.window_exists = lambda target: target == 42
        def query():
            adapter.query_count += 1
            return bytes(state)
        adapter._query_keymap = query
        adapter._modifier_keycodes = lambda: {37}
        adapter.x = type("X", (), {
            "XKeysymToKeycode": staticmethod(lambda _display, sym: 37 if sym == 0xFFE3 else 55),
            "XFlush": staticmethod(lambda _display: 1)})()
        def synth(_display, code, down, _delay):
            adapter.events.append((code, down))
            if down: state[code >> 3] |= 1 << (code & 7)
            else: state[code >> 3] &= ~(1 << (code & 7))
            return 1
        adapter.xt = type("XT", (), {"XTestFakeKeyEvent": staticmethod(synth)})()
        return adapter, state

    def test_x11_diagnostic_refusals_are_exact_and_keep_short_circuit_order(self):
        cases = (
            ("modifier", lambda a: a.paste_with_reason(42, True), (False, "Удерживается клавиша-модификатор"), 0, []),
            ("changed-window", lambda a: (setattr(a, "active_window", lambda: 99), a.paste_with_reason(42))[1],
             (False, "Исходное окно больше не активно"), 0, []),
            ("closed-window", lambda a: (setattr(a, "window_exists", lambda _target: False), a.paste_with_reason(42))[1],
             (False, "Исходное окно закрыто"), 0, []),
        )
        for name, invoke, expected, queries, events in cases:
            with self.subTest(name=name):
                adapter, _ = self._diagnostic_x11()
                self.assertEqual(invoke(adapter), expected)
                self.assertEqual(adapter.query_count, queries)
                self.assertEqual(adapter.events, events)

        adapter, state = self._diagnostic_x11()
        state[91 >> 3] |= 1 << (91 & 7)
        adapter._modifier_keycodes = lambda: {37, 91}
        self.assertEqual(adapter.paste_with_reason(42), (False, "Удерживается клавиша-модификатор"))
        self.assertEqual(adapter.events, [])

        adapter, _ = self._diagnostic_x11()
        adapter.x.XKeysymToKeycode = lambda _d, _sym: 0
        self.assertEqual(adapter.paste_with_reason(42), (False, "Раскладка X11 не предоставляет клавиши для вставки"))
        self.assertEqual((adapter.query_count, adapter.events), (0, []))

        adapter, _ = self._diagnostic_x11()
        adapter._query_keymap = lambda: None
        self.assertEqual(adapter.paste_with_reason(42), (False, "Не удалось проверить состояние клавиатуры X11"))
        self.assertEqual(adapter.events, [])

        adapter, _ = self._diagnostic_x11()
        map_calls = []
        adapter._modifier_keycodes = lambda: (map_calls.append(1), None)[1]
        self.assertEqual(adapter.paste_with_reason(42), (False, "Не удалось проверить состояние клавиатуры X11"))
        self.assertEqual((len(map_calls), adapter.query_count, adapter.events), (1, 1, []))

    def test_x11_diagnostic_rechecks_held_key_synthesis_release_and_success_sequence(self):
        adapter, state = self._diagnostic_x11()
        state[55 >> 3] |= 1 << (55 & 7)
        self.assertEqual(adapter.paste_with_reason(42), (False, "Удерживается клавиша вставки"))
        self.assertEqual(adapter.events, [])

        adapter, _ = self._diagnostic_x11()
        sequence = [bytes(32), None]
        adapter._query_keymap = lambda: (setattr(adapter, "query_count", adapter.query_count + 1), sequence.pop(0))[1]
        self.assertEqual(adapter.paste_with_reason(42), (False, "Не удалось проверить состояние клавиатуры X11"))
        self.assertEqual((adapter.query_count, adapter.events), (2, []))

        adapter, _ = self._diagnostic_x11()
        mapping = iter(({37}, None))
        map_calls = []
        adapter._modifier_keycodes = lambda: (map_calls.append(1), next(mapping))[1]
        self.assertEqual(adapter.paste_with_reason(42), (False, "Не удалось проверить состояние клавиатуры X11"))
        self.assertEqual((adapter.query_count, len(map_calls), adapter.events), (3, 2, [(37, 1), (37, 0)]))

        for failed_event, expected_events, reason in (
            ((37, 1), [(37, 1)], "X11 не смог отправить команду вставки"),
            ((55, 1), [(37, 1), (55, 1), (37, 0)], "X11 не смог отправить команду вставки"),
            ((55, 0), [(37, 1), (55, 1), (55, 0), (37, 0)], "X11 не смог завершить команду вставки"),
        ):
            with self.subTest(failed_event=failed_event):
                adapter, state = self._diagnostic_x11()
                normal = adapter.xt.XTestFakeKeyEvent
                def fail_selected(d, code, down, delay, selected=failed_event):
                    if (code, down) == selected:
                        adapter.events.append((code, down))
                        return 0
                    return normal(d, code, down, delay)
                adapter.xt = type("XT", (), {"XTestFakeKeyEvent": staticmethod(fail_selected)})()
                self.assertEqual(adapter.paste_with_reason(42), (False, reason))
                self.assertEqual(adapter.events, expected_events)

        adapter, _ = self._diagnostic_x11()
        self.assertEqual(adapter.paste_with_reason(42), (True, None))
        self.assertEqual(adapter.events, [(37, 1), (55, 1), (55, 0), (37, 0)])
        self.assertEqual(adapter.query_count, 3)
        self.assertTrue(adapter.paste(42))
        adapter.active_window = lambda: 99
        self.assertEqual(adapter.paste_with_reason(42), (False, "Исходное окно больше не активно"))
        adapter.active_window = lambda: 42
        before = len(adapter.events)
        self.assertEqual(adapter.paste_with_reason(42), (True, None))
        self.assertEqual(adapter.query_count, 9)
        self.assertEqual(adapter.events[before:], [(37, 1), (55, 1), (55, 0), (37, 0)])

    def test_diagnostic_refusals_are_specific_and_success_has_no_stale_reason(self):
        clipboard = FakeClipboard(None)
        adapter = GtkClipboardAdapter(clipboard)
        ok, reason = adapter.paste_safely_with_reason("text", FakeX11(True, clipboard), 1)
        self.assertTrue(ok); self.assertIsNone(reason)
        self.assertEqual(clipboard.text, "text")

        clipboard = FakeClipboard("old")
        clipboard.set_text = lambda text, length: setattr(clipboard, "text", text)
        adapter = GtkClipboardAdapter(clipboard, pump=lambda: None)
        ok, reason = adapter.paste_safely_with_reason("new", FakeX11(True, clipboard), 1)
        self.assertFalse(ok); self.assertIn("подтвердить", reason)
        self.assertEqual(clipboard.text, "new")

        clipboard = FakeClipboard("old")
        adapter = GtkClipboardAdapter(clipboard)
        x11 = FakeX11(True, clipboard, owner_query_hook=lambda query:
            setattr(clipboard, "owner", 999) if query == 2 else None)
        ok, reason = adapter.paste_safely_with_reason("new", x11, 1)
        self.assertFalse(ok); self.assertIn("подтвердить", reason)
        self.assertEqual(clipboard.text, "new")

        clipboard = FakeClipboard("old")
        adapter = GtkClipboardAdapter(clipboard)
        x11 = FakeX11(False, clipboard, lambda: clipboard.set_text("changed", -1))
        ok, reason = adapter.paste_safely_with_reason("new", x11, 1)
        self.assertFalse(ok); self.assertIn("Исходное окно", reason)
        self.assertEqual(clipboard.text, "changed")

        clipboard = FakeClipboard("old")
        adapter = GtkClipboardAdapter(clipboard)
        x11 = FakeX11(True, clipboard)
        ok, reason = adapter.paste_safely_with_reason("new", x11, 1)
        self.assertTrue(ok); self.assertIsNone(reason)
        x11.allow = False
        ok, reason = adapter.paste_safely_with_reason("next", x11, 1)
        self.assertFalse(ok); self.assertEqual(reason, "Исходное окно изменилось или X11 отказал во вставке")

    def _desktop_response(self, auto_insert=True, x11=object(), target=42, clipboard=None, exception=None):
        from giga_pisar_dictation.config import Config
        from giga_pisar_dictation.controller import State
        from giga_pisar_dictation.desktop import DesktopEffects
        class Controller:
            state = State.REQUESTING
            _request_generation = 5
            def response(self, _text, _generation): self.state = State.RESULT
        class Status:
            text = None
            def set_text(self, text): self.text = text
        class View:
            controller = Controller()
            status = Status()
            def refresh(self): pass
            def modifiers_down(self): return False
        effects = DesktopEffects.__new__(DesktopEffects)
        effects.view = View()
        effects.config = Config(auto_insert=auto_insert)
        effects.target, effects.x11 = target, x11
        effects._shutdown = False
        effects.recording_generation = 1
        effects.clipboard = clipboard
        effects.view.controller = Controller()
        if exception is not None:
            class ThrowingClipboard:
                def paste_safely_with_reason(self, *_args): raise RuntimeError(exception)
            effects.clipboard = ThrowingClipboard()
        return effects

    def test_desktop_status_reports_refusal_and_never_leaks_exception_payload(self):
        cases = (
            ("disabled", dict(auto_insert=False), "Автоматическая вставка выключена"),
            ("x11-unavailable", dict(x11=None), "Сеанс X11 недоступен"),
            ("target-missing", dict(target=None), "Исходное окно не определено"),
        )
        for name, options, expected in cases:
            with self.subTest(name=name):
                effects = self._desktop_response(**options)
                effects._response("secret transcript", None, 5)
                self.assertEqual(effects.view.status.text,
                    "Расшифровка готова, не вставлена: " + expected + ". Проверьте и скопируйте вручную.")

        class Diagnostic:
            def paste_safely_with_reason(self, *_args): return False, "Точный безопасный отказ"
        effects = self._desktop_response(clipboard=Diagnostic())
        effects._response("secret transcript", None, 5)
        self.assertIn("Точный безопасный отказ", effects.view.status.text)

        class Legacy:
            def paste_safely(self, *_args): return False
        effects = self._desktop_response(clipboard=Legacy())
        effects._response("secret transcript", None, 5)
        self.assertIn("Не удалось безопасно подтвердить вставку", effects.view.status.text)

        effects = self._desktop_response(exception="SENSITIVE-EXCEPTION-PAYLOAD")
        effects._response("secret transcript", None, 5)
        self.assertIn("Не удалось безопасно выполнить автоматическую вставку", effects.view.status.text)
        self.assertNotIn("SENSITIVE-EXCEPTION-PAYLOAD", effects.view.status.text)
        self.assertNotIn("secret transcript", effects.view.status.text)

    def test_async_desktop_immediate_completion_status_survives_refresh_and_errors_are_sanitized(self):
        class Immediate:
            def paste_safely_async(self, _text, _x11, _target, _modifiers, callback): callback(True, None)
        effects = self._desktop_response(clipboard=Immediate())
        effects.view.refresh = lambda: setattr(effects.view.status, "text", "refresh status")
        effects._response("secret transcript", None, 5)
        self.assertEqual(effects.view.status.text,
            "Команда вставки отправлена, доставка не подтверждена. Проверьте целевое окно.")

        class Throwing:
            def paste_safely_async(self, *_args): raise RuntimeError("PRIVATE PAYLOAD")
        effects = self._desktop_response(clipboard=Throwing())
        effects._response("secret transcript", None, 5)
        self.assertIn("Не удалось безопасно выполнить автоматическую вставку", effects.view.status.text)
        self.assertNotIn("PRIVATE PAYLOAD", effects.view.status.text)

    def test_async_desktop_stale_result_and_disabled_setting_cannot_update_status(self):
        class Deferred:
            callback = None
            def paste_safely_async(self, _text, _x11, _target, _modifiers, callback): self.callback = callback
        for invalidate in ("new-recording", "new-result", "disabled"):
            with self.subTest(invalidate=invalidate):
                clipboard = Deferred()
                effects = self._desktop_response(clipboard=clipboard)
                effects._response("secret transcript", None, 5)
                effects.view.status.text = "newer operation"
                if invalidate == "new-recording": effects.recording_generation += 1
                elif invalidate == "new-result": effects.view.controller._request_generation += 1
                else: object.__setattr__(effects.config, "auto_insert", False)
                clipboard.callback(True, None)
                self.assertEqual(effects.view.status.text, "newer operation")

    def test_desktop_success_status_only_claims_command_sent(self):
        class Diagnostic:
            def paste_safely_with_reason(self, *_args): return True, None
        effects = self._desktop_response(clipboard=Diagnostic())
        effects._response("secret transcript", None, 5)
        self.assertEqual(effects.view.status.text,
            "Команда вставки отправлена, доставка не подтверждена. Проверьте целевое окно.")
        self.assertNotIn("secret transcript", effects.view.status.text)

    def test_old_clipboard_kinds_are_never_read_as_precondition_and_are_overwritten(self):
        for old in ("previous text", None, "image marker", "unknown marker", "unreadable marker"):
            with self.subTest(old=old):
                clipboard = FakeClipboard(old)
                reads = []
                def read():
                    reads.append(clipboard.text)
                    if clipboard.text != "new dictated text": raise OSError("unreadable previous data")
                    return clipboard.text
                clipboard.wait_for_text = read
                adapter = GtkClipboardAdapter(clipboard)
                x11 = FakeX11(True, clipboard)
                self.assertTrue(adapter.paste_safely("new dictated text", x11, 1))
                self.assertEqual(clipboard.text, "new dictated text")
                self.assertEqual(reads, ["new dictated text"])
                self.assertEqual(x11.paste_calls, [(1, False)])

    def test_new_text_readback_failure_refuses_without_restoration(self):
        clipboard = FakeClipboard("old")
        clipboard.wait_for_text = lambda: None
        adapter = GtkClipboardAdapter(clipboard)
        ok, reason = adapter.paste_safely_with_reason("new", FakeX11(True, clipboard), 1)
        self.assertFalse(ok); self.assertIn("подтвердить", reason)
        self.assertEqual(clipboard.text, "new")

    def test_async_owner_confirmation_and_timeout_leave_new_text(self):
        clipboard = FakeClipboard("old"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard); results = []
        adapter.paste_safely_async("new", x11, 1, lambda: False, lambda *r: results.append(r))
        self.assertEqual(results, [])
        clipboard.listeners[0](clipboard, None)
        self.assertEqual(results, [(True, None)])
        self.assertEqual(x11.paste_calls, [(1, False)])
        adapter.shutdown(); self.assertEqual(clipboard.text, "new")

        clipboard = FakeClipboard("old"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: setattr(clipboard, "text", text)
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        results = []; adapter.paste_safely_async("new", FakeX11(True, clipboard), 1, lambda: False,
                                                 lambda *r: results.append(r))
        timers.callbacks[7]()
        self.assertFalse(results[0][0]); self.assertEqual(clipboard.text, "new")

    def test_final_read_reentrant_cancel_or_same_text_owner_change_blocks_x11(self):
        for action in ("cancel", "same-text-owner-change"):
            clipboard = FakeClipboard("old"); timers = FakeTimers()
            clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
            adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
            x11 = FakeX11(True, clipboard); reads = [0]; results = []
            def read():
                reads[0] += 1
                if reads[0] == 2:
                    if action == "cancel": adapter.cancel_pending_paste()
                    else: clipboard.listeners[0](clipboard, None)
                return clipboard.text
            clipboard.wait_for_text = read
            adapter.paste_safely_async("new", x11, 1, lambda: False, lambda *r: results.append(r))
            clipboard.listeners[0](clipboard, None)
            self.assertEqual(x11.paste_calls, [])

    def test_modifier_owner_change_and_new_invocation_during_setup_block_stale_paste(self):
        clipboard = FakeClipboard("old"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard); results = []
        def modifiers():
            clipboard.listeners[0](clipboard, None)
            return False
        adapter.paste_safely_async("new", x11, 1, modifiers, lambda *r: results.append(r))
        clipboard.listeners[0](clipboard, None)
        self.assertEqual(x11.paste_calls, [])

        clipboard = FakeClipboard("old"); timers = FakeTimers()
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard); nested = []
        def owner_query():
            if not nested:
                nested.append(True)
                adapter.copy_text("new copy")
            return clipboard.owner
        x11.clipboard_owner = owner_query
        adapter.paste_safely_async("stale", x11, 1, lambda: False, lambda *_: None)
        self.assertFalse(adapter._pending_pastes)
        self.assertEqual(x11.paste_calls, [])
        self.assertEqual(clipboard.text, "new copy")

    def test_deadline_rechecked_after_final_read_and_overdue_event_cannot_paste(self):
        now = [1.0]; clipboard = FakeClipboard("old"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel,
                                      clock=lambda: now[0])
        x11 = FakeX11(True, clipboard); reads = [0]; results = []
        def read():
            reads[0] += 1
            if reads[0] == 2: now[0] = 1.201
            return clipboard.text
        clipboard.wait_for_text = read
        adapter.paste_safely_async("new", x11, 1, lambda: False, lambda *r: results.append(r))
        clipboard.listeners[0](clipboard, None)
        self.assertFalse(results[0][0])
        self.assertEqual(x11.paste_calls, [])
        self.assertEqual(clipboard.text, "new")

    def test_reentrant_owner_event_during_final_read_cannot_double_paste_and_x11_exception_notifies(self):
        clipboard = FakeClipboard("old"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard); reads = [0]; results = []
        def read():
            reads[0] += 1
            if reads[0] == 2: clipboard.listeners[0](clipboard, None)
            return clipboard.text
        clipboard.wait_for_text = read
        adapter.paste_safely_async("new", x11, 1, lambda: False, lambda *r: results.append(r))
        clipboard.listeners[0](clipboard, None)
        self.assertLessEqual(len(x11.paste_calls), 1)

        clipboard = FakeClipboard("old"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard)
        x11.paste_with_reason = lambda *_: (_ for _ in ()).throw(RuntimeError("private detail"))
        results = []
        adapter.paste_safely_async("new", x11, 1, lambda: False, lambda *r: results.append(r))
        clipboard.listeners[0](clipboard, None)
        self.assertEqual(results, [(False, "Не удалось безопасно выполнить автоматическую вставку")])

    def test_each_async_proof_refusal_notifies_once_cleans_timer_and_never_synthesizes(self):
        cases = ("initial-owner", "owner-after-read", "modifier-generation", "final-owner",
                 "final-content", "same-text-owner-after-read")
        for case in cases:
            with self.subTest(case=case):
                clipboard = FakeClipboard("old"); timers = FakeTimers()
                clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
                adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
                x11 = FakeX11(True, clipboard); results = []
                def query_hook(number):
                    if (case == "initial-owner" and number == 2 or
                        case == "owner-after-read" and number == 3 or
                        case == "final-owner" and number == 4 or
                        case == "same-text-owner-after-read" and number == 5):
                        clipboard.owner = 99
                x11.owner_query_hook = query_hook
                reads = [0]
                def read():
                    reads[0] += 1
                    if case == "final-content" and reads[0] == 2: return "foreign"
                    return clipboard.text
                clipboard.wait_for_text = read
                def modifiers():
                    if case == "modifier-generation": clipboard.listeners[0](clipboard, None)
                    return False
                adapter.paste_safely_async("new", x11, 1, modifiers, lambda *r: results.append(r))
                if case == "modifier-generation": clipboard.listeners[0](clipboard, None)
                else: clipboard.listeners[0](clipboard, None)
                expected_reason = ("Владелец или содержимое буфера обмена изменилось"
                    if case in ("initial-owner", "owner-after-read", "final-content") else "Владелец буфера обмена изменился")
                self.assertEqual(results, [(False, expected_reason)])
                self.assertEqual(x11.paste_calls, [])
                self.assertFalse(adapter._pending_pastes)
                self.assertIn(7, timers.cancelled)

    def test_async_prior_clipboard_matrix_new_text_readback_failure_and_first_repeat(self):
        for old in ("old text", None, "image payload", "unknown payload", "unreadable payload"):
            with self.subTest(old=old):
                clipboard = FakeClipboard(old); timers = FakeTimers(); reads = []
                clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
                def read():
                    reads.append(clipboard.text)
                    if clipboard.text != "recognized": raise OSError("old value read")
                    return clipboard.text
                clipboard.wait_for_text = read
                adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
                x11 = FakeX11(True, clipboard); results = []
                adapter.paste_safely_async("recognized", x11, 1, lambda: False, lambda *r: results.append(r))
                clipboard.listeners[0](clipboard, None)
                self.assertEqual(results, [(True, None)])
                self.assertEqual(reads, ["recognized", "recognized"])
                self.assertEqual(x11.paste_calls, [(1, False)])

        clipboard = FakeClipboard("old"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
        clipboard.wait_for_text = lambda: None
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard); results = []
        adapter.paste_safely_async("new", x11, 1, lambda: False, lambda *r: results.append(r))
        clipboard.listeners[0](clipboard, None)
        self.assertEqual(results, [(False, "Владелец или содержимое буфера обмена изменилось")])
        self.assertEqual(x11.paste_calls, [])

        clipboard = FakeClipboard("old"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        x11 = FakeX11(True, clipboard)
        for _ in range(2):
            result = []
            adapter.paste_safely_async("dictation", x11, 1, lambda: False, lambda *r: result.append(r))
            clipboard.listeners[0](clipboard, None)
            self.assertEqual(result, [(True, None)])
        self.assertEqual(x11.paste_calls, [(1, False), (1, False)])

    def test_async_copy_cancel_stale_callback_and_race_never_restore_old_clipboard(self):
        for mode in ("copy", "shutdown", "foreign-owner", "foreign-content"):
            clipboard = FakeClipboard("old"); timers = FakeTimers()
            clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
            adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
            results = []; x11 = FakeX11(True, clipboard)
            adapter.paste_safely_async("new", x11, 1, lambda: False, lambda *r: results.append(r))
            callback = next(iter(timers.callbacks.values()))
            if mode == "copy": adapter.copy_text("copied")
            elif mode == "shutdown": adapter.shutdown()
            else:
                if mode == "foreign-owner": clipboard.owner = 99
                else: clipboard.text = "other owner data"
                clipboard.listeners[0](clipboard, None)
            callback()
            self.assertEqual(x11.paste_calls, [])
            self.assertNotEqual(clipboard.text, "old")

    def test_sync_x11_refusal_and_shutdown_never_restore_old_clipboard(self):
        clipboard = FakeClipboard("old")
        adapter = GtkClipboardAdapter(clipboard)
        self.assertFalse(adapter.paste_safely("new", FakeX11(False, clipboard), 1))
        self.assertEqual(clipboard.text, "new")
        adapter.shutdown(); self.assertEqual(clipboard.text, "new")

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

    def test_manual_copy_cancels_pending_auto_paste_confirmation(self):
        clipboard = FakeClipboard("old text"); timers = FakeTimers()
        clipboard.set_text = lambda text, length: (setattr(clipboard, "text", text), setattr(clipboard, "owner", 2))
        adapter = GtkClipboardAdapter(clipboard, scheduler=timers.schedule, cancel_timer=timers.cancel)
        results = []
        adapter.paste_safely_async("auto text", FakeX11(True, clipboard), 1, lambda: False,
                                   lambda *r: results.append(r))
        callback = timers.callbacks[7]
        self.assertTrue(adapter.copy_text("manual text", FakeX11(True, clipboard)))
        callback()
        self.assertEqual(results, [])
        self.assertEqual(clipboard.text, "manual text")


if __name__ == "__main__": unittest.main()
