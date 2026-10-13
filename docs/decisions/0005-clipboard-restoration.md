# ADR 0005: Best-effort restoration for automatic paste

- Status: принято; supersedes the destructive automatic-paste policy documented 2026-10-09 (implemented 2026-10-12).
- Automatic insertion is the existing XTest Ctrl+V path, not an alternative input backend. PRIMARY is untouched.
- Asynchronously request the current CLIPBOARD text. Save it only when non-empty; otherwise asynchronously request and save an image if available. Unsupported formats, request errors, and absent data do not prevent paste.
- Install the non-empty transcript with exactly one appended trailing space as CLIPBOARD text and send the existing XTest paste command once. The confirmation readback must equal this final installed text; existing trailing whitespace is not normalized, so another space is appended. Manual Copy remains exact and does not add a space. After 300 ms, restore the saved text/image; clear CLIPBOARD when no snapshot was available. If paste is refused or the operation is cancelled/exits normally, attempt restoration immediately.
- Before XTest, asynchronously confirm the installed transcript and verify the actual X11 CLIPBOARD owner. Before restoration, asynchronously confirm that the transcript and actual owner still match this operation; a delayed GTK owner-change notification alone neither invalidates our ownership proof nor authorizes overwriting a changed clipboard. Never restore over a subsequent external clipboard change or explicit user Copy. A cancelled/stale GTK callback cannot perform a later paste or restoration.
- Bound both snapshot preparation and transcript confirmation with 200 ms timers. Snapshot timeout continues without saved data; confirmation timeout refuses paste and attempts best-effort owned restoration.
- Snapshot and automatic paste preparation use GTK asynchronous request callbacks, not `wait_for_*` or nested GTK event pumping. Snapshot callbacks are ignored after the bounded preparation phase advances. The existing source-window/focus/modifier checks and XTest implementation remain in force.
- This is best effort: it does not preserve every MIME target or the prior clipboard owner; an abnormal process exit can leave the transcript instead of restoring old content. No delivery guarantee is made.
- Explicit Copy remains an intentional replacement of clipboard contents, copies the exact supplied result without a trailing space, and retains its existing synchronous readback contract.

## Consequences

The former destructive policy from the 2026-10-09 implementation is historical only. No xdotool dependency/CLI, character input, fallback backend, or new paste engine is introduced. Tests use clipboard/X11/timer mocks. Пользователь после запуска сообщил: «вроде работает быстро четко». Это подтверждает базовую работу и приемлемую скорость в его сценарии; сохранение изображений, все пограничные сценарии и полная desktop-приёмка этим не подтверждены. Дополнительные реальные тесты агентом не выполнялись.
