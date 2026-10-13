# Пропуск очередного нажатия правого Ctrl после вставки

## Цель
Устранить стабильное чередование неуспешного и успешного запуска рации после вставки, сохранив ownership, физический release, защиту autorepeat и 300 мс хвост.

## Исследование основного агента
Рабочее дерево было чистым, исходная ветка main; создана fix/right-ctrl-mapping-first-press. Прочитаны исходная спецификация, docs/README.md, requirements.md, ADR 0006, предыдущий план, hotkey.py, desktop.py и XTest paste adapter.

Найден воспроизводимый дефект: любой MappingNotify (type 34) без проверки request/изменения фактического binding вызывает gate.reset(), затем _wait_for_held_ptt_key(). Если уведомление находится перед очередным KeyPress в очереди, XQueryKeymap уже видит физически нажатый Ctrl, устанавливается wait_release и новый KeyPress игнорируется. Fake-прогон четырёх циклов с уведомлением перед нечётными нажатиями получил starts=0,1,1,2: пропуск воспроизведён без микрофона, сети и X11.

Это установленный дефект обработки очереди, но наличие именно такого MappingNotify после вставки в пользовательской сессии пока не подтверждено. XTest вставляет левый Ctrl, поэтому прямое совпадение синтетической клавиши с Control_R кодом не следует из кода. Нельзя объявлять исходную пользовательскую причину окончательно доказанной до целевой проверки.

## Границы и пути
- src/giga_pisar_dictation/hotkey.py: корректная обработка MappingNotify request и уведомлений, не меняющих релевантный binding.
- tests/test_hotkey.py, tests/test_desktop_hotkey.py: детерминированные очереди уведомлений/нажатий, повторные циклы RESULT → RECORDING.
- docs/decisions/0006-right-ctrl-push-to-talk.md: согласованное уточнение инвалидации на реальные релевантные изменения вместо любого MappingNotify.
- docs/development.md, docs/README.md, при необходимости docs/manual-testing.md: фактические результаты и ограничения.

Не менять clipboard policy, XTest paste, сервер, системные настройки, установку, автозапуск, хвост записи и посторонний код. Один worker пишет в рабочее дерево; свежий reviewer только читает.

## Решение для согласования
ADR 0006 сейчас предписывает инвалидировать ownership при смене mapping, а реализация делает это при любом уведомлении. Уточнить: нерелевантные уведомления (например MappingPointer) и уведомления без изменения релевантного соответствия не сбрасывают PTT цикл. Реальное изменение Control_R/binding должно по-прежнему безопасно отменять принадлежащую запись и не начинать запись от уже удерживаемой клавиши; mapping races в prepare/commit сохраняют защиту. Worker должен исследовать различие keyboard/modifier request и подобрать минимальное корректное сравнение, не ослабляя toggle и транзакции.

## Шаги и текущий статус
- [x] Проверить рабочее дерево и создать ветку задачи — дерево было чистым, создана `fix/right-ctrl-mapping-first-press`.
- [x] Изучить требования и обработку событий — результаты приведены в разделе «Исследование основного агента».
- [x] Воспроизвести дефект автономно — fake-прогон четырёх нажатий получил starts=0,1,1,2; реальные устройства не затрагивались.
- [x] Сохранить план — этот файл; Plannotator недоступен.
- [x] Получить явное одобрение плана и команду исполнения в чате — пользователь ответил «одобряю» после уточнения плана и чекбоксов.
- [x] Worker исследовал механизм, добавил регрессию, которая падает на baseline (`test_irrelevant_mapping_notify_before_press_does_not_consume_first_ptt_press`, assertion: ожидаемый старт `[17]`, baseline получил `[]`), и реализовал узкое исправление по request и реальному binding delta.
- [x] Покрыты уведомления до/во время/после PTT press, несколько циклов RESULT → RECORDING, autorepeat, held-on-enable/activate, реальный remap, busy/ownerless, tail и prepare/commit/rollback; существующие проверки сохранены.
- [x] Обновлены ADR 0006, docs/development.md и docs/README.md; fake-воспроизведение явно отделено от живой причины/desktop acceptance.
- [x] Worker запустил `PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v` после review fixes — 169 tests passed; `/usr/bin/python3 -m compileall -q src tests scripts` — passed; `git diff --check` — passed.
- [x] Основной агент независимо проверил diff и повторил полный unittest suite — 163 tests passed; compileall и diff-check passed. Дополнительный fake-прогон обнаружил: исчезновение keycode не инвалидирует owner, возврат mapping к прежнему binding не восстанавливает healthy; требуется исправление.
- [x] Свежий read-only reviewer проверил требования, план, diff и тесты — verdict BLOCK: три P1 (gate reset при mapping error, healthy recovery, candidate-only remap away/back) и P2 (неопубликованное исправление в абзаце выпуска). Parent подтвердил candidate away/back fake-прогоном: invalid=False, commit принят.
- [x] Закрыть подтверждённые замечания review через worker: P1 gate reset/prepare invalidation при ошибке mapping; P1 healthy recovery после возврата mapping; P1 sticky invalidation candidate при away/back; P2 README отделяет неопубликованную ветку от выпуска 0.2.8. Worker повторил полный suite — 169 passed, compileall и diff-check — passed.
- [x] Повторно независимо проверены финальный diff и проверки после исправлений: 169 tests passed (12.731 с), compileall и diff-check passed; лог suite `/tmp/giga-ptt-parent-final-tests.log`.
- [x] Свежий read-only review исправлений завершён: все три P1 и P2 закрыты, новых замечаний нет, verdict OK (run e0f58381-b5b5-475a-ad69-4f870191bf0a). Reviewer команды не повторял; фактические результаты подтверждены parent.
- [x] Подготовлен итоговый отчёт: исправлены hotkey.py, два hotkey-теста; обновлены docs/README.md, ADR 0006, docs/development.md и этот план; правило чекбоксов закреплено в AGENTS.md и глобальном AGENTS.md. 169 тестов, compileall и diff-check passed. Живая причина после вставки и GTK/X11 не проверены, установка/публикация/commit не выполнялись.

## Критерии готовности и проверки
- [x] Неизменяющий/нерелевантный MappingNotify перед новым физическим Right Ctrl KeyPress не поглощает запуск из RESULT; fake test проходит четыре последовательных цикла без дополнительного нажатия.
- [x] Реальная смена binding, конфликты, held-on-enable, autorepeat, stale ownership, Busy, tail, invalidation при ошибке, recovery и transactional rollback проверены fake regressions; полный suite — 169 passed.
- [x] `PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v` — worker после review fixes: 169 tests passed.
- [x] `/usr/bin/python3 -m compileall -q src tests scripts` — worker: passed.
- [x] `git diff --check` — worker: passed.
- [x] Полный unittest suite — независимый повтор основным агентом после review-fix: 169 tests passed.
- [x] Compileall — независимый повтор основным агентом после review-fix: passed.
- [x] Diff-check — независимый повтор основным агентом после review-fix: passed.

Живая GTK/X11 проверка остаётся отдельным согласованным сценарием и не входит в эти автономные критерии; без дополнительного разрешения не выполнять реальные grabs, запись, LAN, clipboard/focus effects. Установка/публикация/commit не входят.

## Выпуск 0.2.9 — отдельная команда пользователя
Пользователь явно разрешил «коммить мерж пуш релиз». Установка не разрешена. Версия 0.2.9 — следующий patch после опубликованной 0.2.8; origin/main не содержит новых коммитов относительно локальной main.
- [x] Обновить release-метаданные версии и changelog через worker: версия `0.2.9`; changelog описывает исправление пропуска нажатия правого Ctrl из-за нерелевантных MappingNotify, без заявления о живой приёмке.
- [x] Parent проверил suite — 169 tests passed (12.719 с), compileall, CLI help, desktop-file, сборку .deb 0.2.9, strict validator, lintian policy (только два разрешённых warning), extracted launcher и checksum — passed. Пакет `/tmp/giga-release-0.2.9-lcUM7S/`, лог `/tmp/giga-0.2.9-tests.log`; git diff --check passed.
- [x] Свежий read-only reviewer проверил release diff — замечаний нет, verdict OK (run 4b22d73f-050d-4d34-a40b-197bb04c4863).
- [x] Commit `894b901` на ветке задачи, fast-forward merge main без обхода ограничений, push ветки/main выполнены.
- [x] Аннотированный тег v0.2.9 создан и отправлен; GitHub Actions 38435175707 на `894b901`: build-and-test и publish — success.
- [x] Скачаны .deb и SHA256SUMS; checksum и strict release validator — passed. SHA256 опубликованного .deb: `2404cf38d4fad69799b659a36486b545791384022884b75db5b972844b647c44`.
- [x] Фактический выпуск зафиксирован в docs/README.md, releases.md, development.md на ветке chore/record-v0.2.9-release; итоговый отчёт подготовлен. Пакет не устанавливался. Commit/push этой записи выполняются заключительной Git-командой; их фактический результат отражается в итоговом сообщении.

## Одобрение
Plannotator недоступен в инструментах этой сессии (поиск не вернул tool). Пользователь явно одобрил план в чате («одобряю»); разрешена реализация в согласованных границах. Изменение — один связанный seam обработки MappingNotify в hotkey.py с его регрессиями и документацией; один worker в текущем дереве, без параллельных писателей.
