# Явное Copy заменяет любое содержимое clipboard

## Контекст и одобренное решение
После разрешённой реальной GTK-диагностики копирование тестового текста прошло; пользователь подтвердил Copy без выделения. Предыдущий отказ мог быть связан с нетекстовым содержимым, но его тип не установлен. Пользователь явно одобрил: ручная кнопка Copy заменяет любой clipboard, защита сохраняется только для автовставки. Это согласованное изменение прежнего требования не перезаписывать нетекстовый clipboard при ручном Copy.

## Границы и пути
Только explicit copy, регрессии и docs: src/giga_pisar_dictation/clipboard.py, при необходимости gui.py; tests/test_desktop_safety.py; docs/requirements.md, decisions/0001-desktop-prototype.md, manual-testing.md, development.md и README если затронуты. Исторические планы и initial-spec не переписывать. Feature/desktop-prototype, сохранить существующие dirty/untracked изменения. Без commit/push/install/системных настроек/LAN/микрофона. Автовставка и восстановление её clipboard не менять.

## Подход
- [ ] Свежий worker по .pi/settings.json реализует простое явное копирование полного текста без проверки прежних targets/text/owner, независимо от выделения.
- [ ] Нет результата/невалидный text — отказ без очистки clipboard. При допустимом тексте отменить pending auto-paste restore, записать text, честно подтвердить readback либо сообщить невозможность подтверждения; не обещать unchanged после попытки записи.
- [ ] Тесты ручного Copy: текстовый, пустой, image/nontext/unknown clipboard, no-result, write/readback failure и pending restore; прежние авто-paste refusal/ownership guards остаются.
- [ ] Актуализировать требования/ADR/docs явным разграничением ручного Copy и авто-paste, отметить одобрение нового поведения, не переносить ограничение старых планов на текущее Copy.
- [ ] Parent независимо проверяет код/результаты, fresh read-only reviewer; исправление подтверждённых замечаний и повтор проверок.

## Проверки и критерии
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q src tests
PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation --help
git diff --check

Явное Copy заменяет любое содержимое полным распознанным текстом, без выделения. Только auto-paste защищает нетекстовый clipboard. Секреты/транскрипт не журналировать. Новое поведение на целевом GTK после изменения не считать проверенным по старой диагностике; дальнейшие real clipboard проверки только согласованными тестовыми данными.
