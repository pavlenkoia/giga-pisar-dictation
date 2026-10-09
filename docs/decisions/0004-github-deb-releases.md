# ADR 0004: GitHub Releases для Debian-пакета

- Статус: принято; workflow реализован, первый cloud run и публикация v0.2.3 подтверждены. Run: https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/37937954360. Скачанные Release assets прошли независимую проверку checksum/metadata; desktop acceptance не выполнялась.
- Дополняет ADR 0003: владелец может публиковать бинарный `.deb` в публичных GitHub Releases. Это не выбор open-source лицензии.
- Уведомление copyright допускает owner-published downloads, но сохраняет условия: лицензия не предоставлена; разрешение на перераспространение и повторное использование не предоставлено. Никакая лицензия не выбирается.
- Выпуск запускается только отправленным тегом `vX.Y.Z`; Ubuntu 24.04 runner собирает amd64 пакет. Тег, версия `pyproject.toml` и Debian metadata должны совпадать.
- Тесты и package checks выполняются в read-only job. Только последующий publish job имеет `contents: write`, получает проверенные package/checksum, не checkout-ит и не запускает код репозитория. Повторная публикация существующего Release запрещена.
- Используется встроенный `GITHUB_TOKEN`; ключи и credentials не хранятся в проекте. Реальный Release, установка пакета и desktop acceptance требуют отдельной проверки/разрешений.
