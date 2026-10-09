# ADR 0001: Desktop-прототип GTK/X11

- Статус: принят планом `plans/2026-10-09T04-49Z-first-prototype.md`.
- Решение: Python 3 + system PyGObject; GTK3 UI, Gio.Application session-bus IPC, Soup 3 async HTTP, GStreamer Pulse-compatible WAV capture, X11/XTest paste adapter.
- Credential: отдельный user config `api-key`, 0600 атомарная запись; config directory 0700. Base URL может быть HTTP только на доверенной LAN. Redirects запрещены.
- Внешнюю горячую клавишу назначает пользователь в Cinnamon; приложение не меняет desktop settings и не перехватывает клавиши globally.
- Автовставка проверяет исходное активное окно и текстовый clipboard, никогда не активирует целевое окно. При отказе результат остаётся видимым. Восстановление clipboard допускается только при неизменных GTK owner-change generation и X11 `CLIPBOARD` owner.
- По явному одобрению пользователя ручная кнопка Copy безусловно заменяет любое содержимое clipboard полным непустым распознанным текстом, независимо от выделения; пустой/отсутствующий результат ничего не записывает, успех подтверждается readback. Это исключение действует только на ручной Copy и не меняет safety-проверки auto-paste.
- X11 calls use pointer-sized ctypes signatures, a bounded BadWindow error handler, live keymap/modifier checks and XKeysymToKeycode. Files/config are opened by no-follow descriptors and validated by fstat.
- Ограничения: Wayland, server-side cancellation, универсальное подтверждение paste, неизвестные серверные лимиты; реальная desktop/LAN приёмка ещё не выполнена.
