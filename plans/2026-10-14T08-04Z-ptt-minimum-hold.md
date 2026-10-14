# Защита «Рации» от короткого нажатия

## Цель и границы

Реализовать согласованное в docs/requirements.md правило: принадлежащая PTT запись отправляется только при суммарном удержании правого Ctrl не менее 700 мс. Хвост 300 мс и промежутки между удержаниями исключаются. Повторное нажатие в хвосте продолжает ту же запись и суммирует удержания. Короткая запись отменяется с удалением аудио и возвратом в IDLE без ошибки.

Без VAD, сжатия, изменений API, конфигурации, toggle или ручного/CLI start. Без установки, выпуска, commit/push и реальных микрофонных, сетевых, clipboard или X11 сценариев.

## Исследование и пути

- [x] Прочитаны docs/initial-spec.md, docs/README.md, docs/requirements.md, ADR 0006 и команды из docs/development.md; исследован текущий PTT tail в desktop.py.
- [x] Проверена ветка chore/ptt-minimum-hold-decision. Единственное исходное изменение — ранее согласованная запись решения в docs/requirements.md; сохранить её.

Основные пути: src/giga_pisar_dictation/desktop.py и lifecycle-регрессии в tests/test_audio_lifecycle.py/tests/test_desktop_hotkey.py. Документация: docs/requirements.md, docs/decisions/0006-right-ctrl-push-to-talk.md, docs/development.md, docs/manual-testing.md. Проверен PushToTalkGate callback path в hotkey.py: release доставляется синхронно для активного цикла, повторное событие без нового press игнорируется; изменение gate/token не требуется.

## Решения

Использовать целочисленные монотонные часы nanosecond precision с подменой в тестах. Начало интервала — принятый keydown до запуска recorder, не завершение запуска. Учёт привязать к recording_generation и ownership; неуспешный start/Busy не создаёт интервал. При release закрывать интервал один раз; повторный stale release не увеличивает сумму. Решение stop/cancel принимается в конце существующего хвоста, чтобы короткий первый интервал мог продолжиться повторным нажатием. Ровно 700 000 000 нс допускается без float rounding. При отмене/ошибке/лимите/shutdown учёт очищается; callbacks старого поколения не влияют на новое. Сохранить действующие проверки binding/ownership.

## Исполнение

- [x] Пользователь одобрил план и исполнение в чате («одобряю»); инструмент Plannotator недоступен.
- [x] Свежий builtin worker реализовал ограниченную правку, тесты и документацию.
- [x] Worker выполнил автономные проверки и зафиксировал фактические результаты отдельно от приёмки.
- [x] Основной агент повторно проверил исправленный diff: целочисленные часы и новые lifecycle-регрессии; 175 tests passed (12.757 s), compileall и diff-check passed.
- [x] Первый read-only review сообщил BLOCK по P1/P2; worker исправил их. Основной агент повторил проверки; свежий финальный reviewer 5b570fc1-8f44-4764-bb33-c6bc8dcf8053 подтвердил устранение обоих замечаний, новых дефектов нет, verdict OK. Reviewer проверял diff read-only, команды не повторял.

## Проверки и приёмка

- [x] Fake-clock monotonic_ns тесты: меньше 700 мс отменяется; ровно 700 мс (включая baseline 10 000 000 000 нс) и больше отправляются; многократные интервалы суммируются точно, tail не учитывается.
- [x] Повторное нажатие суммирует интервалы; сохранённый callback старого tail вызван после re-press и не завершает запись; duplicate release остаётся инертным.
- [x] Cancel/error/limit очищают учёт перед новой generation; shutdown reset проверен отдельно. Fake recorder startup delay подтверждает timestamp до запуска recorder.
- [x] Короткая запись через fake recorder/client действительно удаляется без transcribe, Controller возвращается в IDLE без ошибки.
- [x] PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v — 175 tests passed.
- [x] /usr/bin/python3 -m compileall -q src tests scripts — passed.
- [x] git diff --check — passed.
- [x] Документы отмечают реализованное правило и действительные результаты; docs/manual-testing.md содержит целевой ручной сценарий, не объявленный выполненным.
- [x] Повторная независимая проверка и свежий read-only review завершены; финальный отчёт подготовлен. Реальная GTK/X11 приёмка не выполнялась, установка/выпуск/commit не выполнялись.
