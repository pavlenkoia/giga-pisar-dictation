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

## Первый устанавливаемый desktop `.deb` (2026-10-09)

`/usr/bin/python3 scripts/build-deb.py` создал `dist/giga-pisar-dictation_0.2.0_amd64.deb` (amd64, local artifact, ignored by git). Version 0.2.0 читается из единственного источника `pyproject.toml`. Сборка использует только `dpkg-deb --root-owner-group`, не требует root, network/download, установки dependencies или запуска обычного launcher. `dpkg-deb --info/--contents` подтвердили Depends, root/root owner, directory mode 0755, module/desktop/icon/docs mode 0644, launcher mode 0755; присутствуют только application source/assets/docs, нет tests, keys, config, audio, pycache или maintainer scripts. Пакет распакован во временный каталог; relocated launcher `--help` завершился успешно с cwd вне checkout и `PYTHONPATH` удалён. Это проверка импорта/help, не запуск desktop окна.

Зависимости сверены по локально доступным Linux Mint 22.3 / Ubuntu noble (24.04) repository metadata через `apt-cache show`/`apt-cache policy` — все точные package names из control доступны: `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-3.0`, `gir1.2-soup-3.0`, `gir1.2-gstreamer-1.0`, `gir1.2-ayatanaappindicator3-0.1`, `gstreamer1.0-plugins-base`, `gstreamer1.0-plugins-good`, `gstreamer1.0-pulseaudio`, `libx11-6`, `libxtst6`, `python3 (>= 3.10)`. `gstreamer1.0-pulseaudio` доступен в Noble universe как transitional package; имя сохранено согласно плану. Проверка metadata не скачивала и не устанавливала пакеты и не является проверкой установки в чистую Mint систему.

Фактические автономные результаты: `PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v` — 88 passed; `/usr/bin/python3 -m compileall -q src tests scripts` — passed; `PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation --help` — passed; `git diff --check` — passed; package builder, `dpkg-deb --info`, `dpkg-deb --contents`, extract/relocated launcher help — passed; `desktop-file-validate packaging/org.gigapisar.Dictation.desktop` — passed. `lintian dist/giga-pisar-dictation_0.2.0_amd64.deb` завершился с exit 0 и только двумя warnings:

- `copyright-without-copyright-notice`: owner approved that no license is granted, package is for personal use, and no holder is named. We do not fabricate a copyright holder or select an open-source license to silence this warning.
- `no-manual-page`: a man page was not part of this private desktop package scope.

Maintainer is the owner-supplied `Local package <pavlenko@it-tian.ru>`; local changelog is factual for version 0.2.0. The package remains private/personal; no publication or license grant is implied.

При первом suite run полный `unittest discover` проявил порядок-зависимую Soup cancellation failure: GIO вернул локализованную строку `Операция была отменена`, тогда как существующий API helper распознаёт английский `cancel`; из-за этого тест увидел `server is unavailable`. Тот же API module/test проходил изолированно, а временный `git archive HEAD` тест baseline прошёл 57/57. Источник взаимодействия выявлен в новом `test_tray_lifecycle.py`: eager module-level GTK import перед Soup tests в discovery менял глобальное GI/GTK состояние. GTK import перенесён в test `setUp`, после API suite; полный текущий набор теперь проходит 86/86 без изменения API semantics. Повторная suite проверка обязательна при будущей сборке/ревью.

Не выполнены: установка/запуск из Mint menu, tray click/host-loss в реальной Cinnamon session, login autostart, package update/removal, audio/LAN/clipboard/focus/hotkey desktop acceptance. Полный безопасный сценарий перечислен в `manual-testing.md`; установка в текущем ходе не разрешалась.

### Regression fixes after read-only release review

- Ayatana/AppIndicator does not expose a `secondary-activate` signal. `DesktopWindow._create_indicator` now targets the retained Show window menu item through `set_secondary_activate_target`; a faithful fake namespace rejects unsupported signal names and verifies the production wiring without creating a real Indicator or connecting to a session tray.
- Five-minute recording-limit cancellation refreshes the view after Controller reaches IDLE and before the user-facing limit message, so the rendered state icon returns to idle. The regression asserts the indicator's final icon and message.
- Requirements now place Check server in the main window after Settings are saved, and preserve the AppIndicator ordinary-click menu limitation, supported Show window paths, unknown-host fallback, and first-run Settings behavior.
- After these changes, the full suite passed 88 tests; `compileall`, CLI help, `git diff --check`, package build/extraction checks, desktop-file validation, and lintian were repeated. Lintian remains exit 0 with the two warnings listed above.

### Settings fallback при недоступном autostart (2026-10-09)

Версия проекта обновлена до 0.2.1. Если проверка безопасного состояния autostart завершается ошибкой, Settings открывается с предупреждением, переключатель autostart недоступен, а Save передаёт `autostart_enabled=None`; остальные settings сохраняются без чтения/записи autostart. Реальные пользовательские каталоги не читались и не изменялись. Полный набор прошёл: 90 unittest tests; compileall, CLI help, `git diff --check`, сборка `.deb`, `dpkg-deb --info/--contents`, extraction и relocated launcher help без `PYTHONPATH`, desktop-file validation. Lintian завершился успешно с теми же двумя ранее согласованными warnings: `copyright-without-copyright-notice` и `no-manual-page`. Пакет `dist/giga-pisar-dictation_0.2.1_amd64.deb` не устанавливался; GUI/session acceptance остаётся непроверенной.
