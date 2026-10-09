# Разработка и проверка

Системные GI библиотеки и GTK/GStreamer plugins нужны из ОС; зависимости не устанавливаются этим проектом.

Из корня checkout:

```sh
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q src tests
PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation --help
git diff --check
```

Soup API unit tests используют локальный HTTP сервер с фиктивным ключом. Gio IPC тест оборачивает процесс теста в `dbus-run-session`, создаёт временный owner и проверяет no-owner refusal и удалённую команду через CLI. Автотесты не запускают запись/GTK clipboard.

Не запускать реальные микрофонные, API/LAN, глобальные shortcut или вставочные тесты без отдельно согласованного сценария. `docs/manual-testing.md` описывает границы сценария.

## Фактические результаты реализации (2026-10-09)

Предыдущая проверка Copy: 27 unittest прошли; compileall, CLI help и `git diff --check` успешны. Текущее ручное Copy безусловно заменяет clipboard только для допустимого непустого результата; проверки автоматической вставки остаются отдельными. Ниже приведены актуальные команды проверки; реальные clipboard/desktop effects не запускались.

## Audio finalization regression (2026-10-09)

`GstRecorder` использует signal watch на GLib bus как единственного потребителя EOS/ERROR. Stop отправляет EOS и ждёт уведомления через bounded condition wait, без конкурирующего `timed_pop_filtered`; cancel будит ожидающую финализацию, cleanup идемпотентен. Добавлены регрессии EOS, ERROR, timeout, cancel/repeated cleanup, сигнализируемое ожидание начала EOS до cancel, замена поколения записи и shutdown во время финализации. Синтетическая проверка реального GStreamer запускает непрерывный `audiotestsrc is-live=true`, ждёт первый buffer через pad probe, затем вызывает stop-driven EOS под активным GLib MainLoop и проверяет временный приватный WAV как mono PCM16/16k. Это не использует `pulsesrc`, микрофон, сеть, clipboard или фокус, и не является полной GTK/X11 desktop-приёмкой. Реальный microphone/desktop сценарий остаётся непроверенным.

## Встроенная горячая клавиша (2026-10-09)

Fake-backend tests cover accelerator/config compatibility, partial BadAccess rollback, lock-mask variants, mapped key/modifier updates, buffered key events, repeat suppression, target capture, wait-for-release dispatch, transactional rebind/save failure, disable/close cleanup, and late callbacks. Tests do not register real grabs, touch focus, clipboard, microphone, or LAN. Results after reviewer-driven regression fixes: 57 unittest tests passed; compileall completed successfully; CLI `--help` displayed the existing start/stop/cancel/status/toggle commands; `git diff --check` passed. Fake backends were used for all shortcut tests, including target preservation across stop/Busy, invalidation of in-flight cycles on mapping/rebind failures, zero keycode rejection, buffered events after startup/query synchronization, physical-grab overlap transactions, and truthful mapping-health failure/recovery. The agent did not perform target GTK/X11 acceptance or real global grabs. The user subsequently reported that the shortcut works; this confirms basic manual operation, not every edge case in the acceptance scenario.

Основной агент независимо повторил все четыре проверки: 57 тестов прошли, compileall, CLI help и diff-check успешны. После трёх раундов read-only ревью подтверждённые P1 исправлены; заключительный вердикт — OK с оставшимся P2. Если MappingNotify приходит во время commit переназначения, подготовленный keycode может устареть, а commit и DesktopEffects всё равно сообщат «active», перезаписав ошибку mapping. Этот сценарий не исправлен: нужна повторная валидация подготовленного binding и статус по фактическому healthy. Пользователь подтвердил базовую работу shortcut и явно согласовал закрытие плана с этим некритичным P2 без исправления. План закрыт с известным ограничением; полный набор ручных edge-case сценариев не подтверждён. Статус «active» сам по себе не доказывает работоспособность при этой гонке.
