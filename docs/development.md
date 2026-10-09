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

Не запускать реальные микрофонные, API/LAN или вставочные тесты без отдельно согласованного сценария. Для текущего плана разрешены короткая запись и вставка только в специально открытое тестовое поле. `docs/manual-testing.md` описывает границы сценария и shortcut assignment.

## Фактические результаты реализации (2026-10-09)

Предыдущая проверка Copy: 27 unittest прошли; compileall, CLI help и `git diff --check` успешны. Текущее ручное Copy безусловно заменяет clipboard только для допустимого непустого результата; проверки автоматической вставки остаются отдельными. Ниже приведены актуальные команды проверки; реальные clipboard/desktop effects не запускались.

## Audio finalization regression (2026-10-09)

`GstRecorder` использует signal watch на GLib bus как единственного потребителя EOS/ERROR. Stop отправляет EOS и ждёт уведомления через bounded condition wait, без конкурирующего `timed_pop_filtered`; cancel будит ожидающую финализацию, cleanup идемпотентен. Добавлены регрессии EOS, ERROR, timeout, cancel/repeated cleanup, сигнализируемое ожидание начала EOS до cancel, замена поколения записи и shutdown во время финализации. Синтетическая проверка реального GStreamer запускает непрерывный `audiotestsrc is-live=true`, ждёт первый buffer через pad probe, затем вызывает stop-driven EOS под активным GLib MainLoop и проверяет временный приватный WAV как mono PCM16/16k. Это не использует `pulsesrc`, микрофон, сеть, clipboard или фокус, и не является полной GTK/X11 desktop-приёмкой. Реальный microphone/desktop сценарий остаётся непроверенным.
