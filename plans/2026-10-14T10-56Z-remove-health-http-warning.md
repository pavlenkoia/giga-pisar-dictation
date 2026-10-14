# Убрать предупреждение HTTP и выпустить 0.2.11

## Цель и границы
Убрать безусловное предупреждение HTTP из результата «Проверить сервер» без добавления проверки схемы URL. Сохранить сам health request, ошибки и сообщение об отсутствующем ключе. Не менять TLS, API, сервер, настройки ОС, микрофон или clipboard.

Пути: src/giga_pisar_dictation/desktop.py, tests/ (узкие fake-регрессии), pyproject.toml, scripts/build-deb.py, README.md, docs/README.md, docs/requirements.md при необходимости, docs/development.md, docs/releases.md, этот план.

## Согласование
Пользователь одобрил в чате короткий план «убрать предупреждение → обновить документацию и версию → проверить и провести review → опубликовать релиз», после прямой команды на выпуск. Plannotator недоступен (нет CLI/tool). Публикация нового тега, commit и push разрешены командой на релиз; merge не требуется.

## Шаги и проверки
- [x] Исследовать причину и проверить дерево — предупреждение hardcoded в DesktopEffects.health, main был чистым; создана fix/remove-health-http-warning. Текущий опубликованный выпуск v0.2.10.
- [x] Согласовать краткий план — пользователь ответил «да».
- [x] Worker: удалить предупреждение из всех health-веток, добавить fake-регрессии для HTTP/HTTPS success/error/no-key, поднять версию 0.2.11 и changelog, обновить документацию без преждевременного заявления публикации — реализовано; версия помечена как локальная и неопубликованная.
- [x] Worker: unittest, compileall, diff-check; отчёт с фактическими результатами — 178 tests passed, compileall и `git diff --check` passed.
- [x] Основной агент: независимо просмотрен diff, 178 tests passed, CLI help, compileall, diff-check, сборка, strict release validator, desktop-file validation, lintian policy (два известных warnings), extracted launcher help и checksum — passed. Логи /tmp/giga-0.2.11-*.log.
- [x] Свежий read-only reviewer: требования, план и diff проверены; замечаний нет, verdict OK. Run fa617d81-803f-47a3-ac5a-2fe320df1c31; команды reviewer не повторял.
- [ ] Основной агент: commit, push ветки и новый annotated tag v0.2.11; дождаться build-and-test/publish, скачать assets и проверить checksum/metadata.
- [ ] Обновить docs/README.md и docs/releases.md фактическими результатами выпуска; зафиксировать документацию.

## Готовность и ограничения
- [x] В status больше нет предупреждения HTTP, успех/ошибки/отсутствие ключа сохранены, новых URL-ветвлений нет — подтверждено diff и fake-тестами.
- [ ] Публичный v0.2.11 содержит проверенные .deb и SHA256SUMS.
- [ ] Финальный отчёт: ссылка, изменения, проверки, docs и ограничения. Настоящая GTK/X11-приёмка и установка не выполняются; fake-тесты её не заменяют.
