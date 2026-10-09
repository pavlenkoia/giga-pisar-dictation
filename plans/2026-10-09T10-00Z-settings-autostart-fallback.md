# Settings: доступность при недоступном autostart

## Цель и подтверждённая причина
На целевом хосте ~/.config/autostart принадлежит пользователю, mode 0775; собственного desktop-файла нет. AutostartFile отвергает group-writable каталог, а settings_dialog возвращается до открытия диалога. Это блокирует URL/ключ из-за независимой необязательной функции.

## Подход и границы
Не менять реальные права каталогов, пользовательские файлы или защиту autostart. При ошибке проверки autostart открывать Settings с понятным предупреждением и недоступным переключателем автозапуска; остальные настройки доступны. Save передаёт autostart_enabled=None при недоступном адаптере: не читать/писать его, сохранить существующие проверки остальных настроек. Обновить пакет до 0.2.1, чтобы исправление можно установить как обновление. Не устанавливать автоматически, не запускать desktop/микрофон/LAN/clipboard/hotkeys, не делать commit/push. Сохранить все текущие изменения ветки chore/desktop-release-requirements.

## Пути и переиспользование
- src/giga_pisar_dictation/gui.py: settings_dialog, существующие Settings и safe error UI.
- src/giga_pisar_dictation/desktop.py: save_settings уже поддерживает autostart_enabled=None; менять лишь при доказанной необходимости.
- tests/test_autostart.py, tests/test_tray_lifecycle.py: fake GTK и temporary XDG, регрессия production dialog/Save.
- pyproject.toml: 0.2.1; scripts/build-deb.py переиспользовать без второго источника версии.
- README.md, docs/development.md, docs/manual-testing.md, docs/requirements.md: обновить релевантные ссылки/сведения о поправке и фактических проверках.

## Шаги
1. После явного одобрения передать свежему встроенному worker с моделью из .pi/settings.json.
2. Добавить регрессию: unsafe autostart directory/entry не блокируют Settings и остальные Save; disabled checkbox не означает, что существующий автозапуск выключен. Ошибка отображается без секретов. Cancel ничего не меняет.
3. Выполнить исправление UI без ослабления filesystem policy; сохранить отказ безопасной записи autostart и существующие rollback-тесты.
4. Версия 0.2.1, сборка .deb без установки, обновление docs.
5. Родитель независимо проверяет diff/проверки; свежий read-only reviewer, исправление подтверждённых замечаний.

## Проверки и готовность
- PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
- /usr/bin/python3 -m compileall -q src tests scripts
- PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation --help
- git diff --check
- /usr/bin/python3 scripts/build-deb.py; dpkg-deb --info/--contents dist/giga-pisar-dictation_0.2.1_amd64.deb
- desktop-file-validate packaging/org.gigapisar.Dictation.desktop; lintian нового пакета (2 прежних согласованных warnings отдельно отметить).
- Fake dialog tests проверяют Settings и Save с недоступным autostart, а временные XDG тесты доказывают неизменность файла/прав каталога и config/key security.
- Итог: исправление и пакет проверены, reviewer замечания обработаны; установка/реальная GTK-проверка пользователем отдельно, без заявления завершённой desktop-приёмки.

## Согласование
Plannotator недоступен после завершения предыдущего плана; требуется явное одобрение в чате на реализацию и patch-релиз 0.2.1.
