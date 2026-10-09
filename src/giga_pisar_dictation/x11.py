"""X11 focus and XTest paste adapter with explicit 64-bit ctypes signatures."""
from __future__ import annotations
import ctypes
import ctypes.util
import threading


class XModifierKeymap(ctypes.Structure):
    _fields_ = [("max_keypermod", ctypes.c_int), ("modifiermap", ctypes.POINTER(ctypes.c_ubyte))]


class XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong), ("class", ctypes.c_int), ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long), ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long), ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


_ERROR_LOCK = threading.RLock()
_X_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


class X11Adapter:
    def __init__(self, display=None):
        name, xtest = ctypes.util.find_library("X11"), ctypes.util.find_library("Xtst")
        if not name or not xtest: raise RuntimeError("Библиотеки XTest для X11 недоступны")
        self.x, self.xt = ctypes.CDLL(name), ctypes.CDLL(xtest)
        self._set_signatures()
        self.display = self.x.XOpenDisplay(display)
        if not self.display: raise RuntimeError("Не удалось подключиться к дисплею X11")

    def _set_signatures(self):
        x = self.x
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]; x.XOpenDisplay.restype = ctypes.c_void_p
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]; x.XCloseDisplay.restype = ctypes.c_int
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]; x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]; x.XInternAtom.restype = ctypes.c_ulong
        x.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]; x.XGetSelectionOwner.restype = ctypes.c_ulong
        x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
            ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
        x.XGetWindowProperty.restype = ctypes.c_int
        x.XFree.argtypes = [ctypes.c_void_p]; x.XFree.restype = ctypes.c_int
        x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XWindowAttributes)]
        x.XGetWindowAttributes.restype = ctypes.c_int
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]; x.XSync.restype = ctypes.c_int
        x.XSetErrorHandler.argtypes = [_X_ERROR_HANDLER]; x.XSetErrorHandler.restype = ctypes.c_void_p
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]; x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char)]; x.XQueryKeymap.restype = ctypes.c_int
        x.XGetModifierMapping.argtypes = [ctypes.c_void_p]; x.XGetModifierMapping.restype = ctypes.POINTER(XModifierKeymap)
        x.XFreeModifiermap.argtypes = [ctypes.POINTER(XModifierKeymap)]; x.XFreeModifiermap.restype = ctypes.c_int
        x.XFlush.argtypes = [ctypes.c_void_p]; x.XFlush.restype = ctypes.c_int
        self.xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.xt.XTestFakeKeyEvent.restype = ctypes.c_int

    def active_window(self):
        root = self.x.XDefaultRootWindow(self.display)
        atom = self.x.XInternAtom(self.display, b"_NET_ACTIVE_WINDOW", 1)
        actual = ctypes.c_ulong(); fmt = ctypes.c_int(); count = ctypes.c_ulong(); after = ctypes.c_ulong(); data = ctypes.c_void_p()
        status = self.x.XGetWindowProperty(self.display, root, atom, 0, 1, 0, 33,
            ctypes.byref(actual), ctypes.byref(fmt), ctypes.byref(count), ctypes.byref(after), ctypes.byref(data))
        if status != 0 or not data.value: return None
        if actual.value != 33 or fmt.value != 32 or count.value < 1:
            self.x.XFree(data); return None
        try: return ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0]
        finally: self.x.XFree(data)

    def window_exists(self, window):
        if not window: return False
        attributes = XWindowAttributes()
        with _ERROR_LOCK:
            handler = _X_ERROR_HANDLER(lambda _display, _event: 0)
            previous = self.x.XSetErrorHandler(handler)
            try:
                result = self.x.XGetWindowAttributes(self.display, window, ctypes.byref(attributes))
                self.x.XSync(self.display, 0)
                return bool(result)
            finally:
                self.x.XSetErrorHandler(ctypes.cast(previous, _X_ERROR_HANDLER) if previous else _X_ERROR_HANDLER())

    def clipboard_owner(self):
        atom = self.x.XInternAtom(self.display, b"CLIPBOARD", 0)
        owner = self.x.XGetSelectionOwner(self.display, atom)
        return owner or None

    def _query_keymap(self):
        keys = ctypes.create_string_buffer(32)
        if not self.x.XQueryKeymap(self.display, keys): return None
        return keys.raw

    def _modifier_keycodes(self):
        mapping = self.x.XGetModifierMapping(self.display)
        if not mapping: return None
        try:
            maximum = mapping.contents.max_keypermod
            values = mapping.contents.modifiermap
            if maximum <= 0 or not values: return None
            return {int(values[index]) for index in range(8 * maximum) if values[index]}
        finally:
            self.x.XFreeModifiermap(mapping)

    @staticmethod
    def _is_down(keymap, keycode):
        return bool(keymap[keycode >> 3] & (1 << (keycode & 7)))

    def modifiers_down(self, keymap=None, modifier_keycodes=None, ignore=()):
        keymap = self._query_keymap() if keymap is None else keymap
        modifier_keycodes = self._modifier_keycodes() if modifier_keycodes is None else modifier_keycodes
        # If the server cannot report its mapping/state, fail closed rather than risk releasing a user's key.
        if keymap is None or modifier_keycodes is None: return True
        return any(code not in ignore and self._is_down(keymap, code) for code in modifier_keycodes)

    def paste(self, expected_window, modifiers_down=False):
        return self.paste_with_reason(expected_window, modifiers_down)[0]

    def paste_with_reason(self, expected_window, modifiers_down=False):
        if modifiers_down: return False, "Удерживается клавиша-модификатор"
        if self.active_window() != expected_window: return False, "Исходное окно больше не активно"
        if not self.window_exists(expected_window): return False, "Исходное окно закрыто"
        control = int(self.x.XKeysymToKeycode(self.display, 0xFFE3))
        v_key = int(self.x.XKeysymToKeycode(self.display, ord("v")))
        if not control or not v_key: return False, "Раскладка X11 не предоставляет клавиши для вставки"
        modifier_codes = self._modifier_keycodes()
        keymap = self._query_keymap()
        if keymap is None or modifier_codes is None: return False, "Не удалось проверить состояние клавиатуры X11"
        if self.modifiers_down(keymap, modifier_codes): return False, "Удерживается клавиша-модификатор"
        if self._is_down(keymap, control) or self._is_down(keymap, v_key): return False, "Удерживается клавиша вставки"

        pressed = []
        success = False
        releases_ok = True
        try:
            # Recheck immediately before synthesis; release only key-down events this call accepted.
            keymap = self._query_keymap()
            if keymap is None: return False, "Не удалось проверить состояние клавиатуры X11"
            if self.modifiers_down(keymap, modifier_codes): return False, "Удерживается клавиша-модификатор"
            if self._is_down(keymap, control) or self._is_down(keymap, v_key): return False, "Удерживается клавиша вставки"
            if not self.xt.XTestFakeKeyEvent(self.display, control, 1, 0): return False, "X11 не смог отправить команду вставки"
            pressed.append(control)
            keymap = self._query_keymap()
            modifier_codes = self._modifier_keycodes()
            if keymap is None or modifier_codes is None: return False, "Не удалось проверить состояние клавиатуры X11"
            if self.modifiers_down(keymap, modifier_codes, ignore=(control,)): return False, "Удерживается клавиша-модификатор"
            if self._is_down(keymap, v_key): return False, "Удерживается клавиша вставки"
            if not self.xt.XTestFakeKeyEvent(self.display, v_key, 1, 0): return False, "X11 не смог отправить команду вставки"
            pressed.append(v_key)
            success = True
        finally:
            for keycode in reversed(pressed):
                if not self.xt.XTestFakeKeyEvent(self.display, keycode, 0, 0): releases_ok = False
            if pressed: self.x.XFlush(self.display)
        if not releases_ok: return False, "X11 не смог завершить команду вставки"
        return (True, None) if success else (False, "X11 не смог отправить команду вставки")

    def close(self):
        if self.display:
            self.x.XCloseDisplay(self.display)
            self.display = None
