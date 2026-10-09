# Ручная настройка shortcut и будущая desktop-проверка

## Shortcut (вручную, без изменений приложением)

1. В Cinnamon открыть **System Settings → Keyboard → Shortcuts → Custom Shortcuts**.
2. Добавить пользовательский ярлык с командой `PYTHONPATH=/путь/к/checkout/src /usr/bin/python3 -m giga_pisar_dictation toggle`.
3. Назначить сочетание, только предварительно проверив конфликты. `Ctrl+Alt+Space` — кандидат, не настройка по умолчанию и не обещание свободного сочетания.
4. Можно назначить отдельные ярлыки с последним аргументом `start`, `stop`, `cancel`, `status`. App не регистрирует глобальный hotkey и не меняет Cinnamon.

## Desktop/API acceptance (не завершена)

Copy button behavior is covered by unit tests with a fake clipboard: explicit Copy overwrites empty, text, nontext (including image), or unknown clipboard contents with the complete non-empty output, without requiring a selection. Empty/no-result input performs no write. Success is reported only when readback matches; write/readback failures report inability to confirm. Copy cancels pending auto-paste restoration so it cannot later undo the user's explicit action. This policy is only for manual Copy: auto-paste retains text-only clipboard and ownership safety checks. Real GTK/X11 clipboard interaction and a paste into a dedicated test field have not been performed; unit tests do not establish desktop acceptance.

Только в целевой X11 сессии и специально открытом тестовом текстовом поле: ввести локально ключ через masked Settings entry; проверить `/health`; короткую тестовую диктовку; отмену; занятость; вставку кириллицы; изменение фокуса/закрытие тестового окна; нетекстовый clipboard; смену ownership; восстановление test clipboard; tray/window; WAV cleanup. Не использовать чужое окно или пользовательское clipboard. Ключ, аудио и текст не включать в отчёт.

Не выполнять длительную запись, нагрузочные тесты или изменения сервера. Автотесты/моки не являются GTK/X11 или реальной LAN приёмкой.

### Текущий результат

Реальная инициализация GTK и read-only X11-проверки прошли; полный сценарий записи/распознавания/вставки не выполнен. Штатный загрузчик не обнаружил сохранённый локальный ключ, выбранного WAV нет. Сеть, микрофон, clipboard и фокус при этой проверке не изменялись. Подробные результаты автоматических проверок и ревью — в `development.md`.

Для продолжения запустить приложение из checkout, открыть **Settings**, ввести новый ключ в **API key**, нажать **Save** и убедиться, что UI сообщает об успешном сохранении (не присылать ключ в чат). Приложение ищет `api-key` в `$XDG_CONFIG_HOME/giga-pisar-dictation/`, по умолчанию `~/.config/giga-pisar-dictation/`; каталог должен иметь права `0700`, файл — `0600`. Не раскрывать содержимое файла для диагностики. Затем проверить **Check server** и провести согласованный короткий сценарий исключительно в отдельном тестовом поле с тестовым clipboard.

Остаточные ограничения: HTTP не шифрует ключ/аудио; реальные серверные лимиты неизвестны; проверка XID не подтверждает конкретное поле; гонку между проверкой фокуса/клавиш и XTest нельзя полностью исключить; универсального подтверждения paste нет, задержка восстановления clipboard ограничена.
