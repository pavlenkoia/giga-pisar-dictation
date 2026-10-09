# Автоматические .deb-выпуски в GitHub Releases

Статус: реализация завершена и принята локально; независимое read-only ревью — OK with notes. Реальный GitHub Actions run и публикация ожидают отдельной команды.
Ветка: `chore/github-deb-releases`.

## Цель

После отправки тега `vX.Y.Z` GitHub Actions проверяет проект, собирает существующим сборщиком amd64 .deb и публикует GitHub Release с пакетом и `SHA256SUMS`. Пользователь скачивает пакет из Releases, не из временных Actions artifacts.

## Исходное состояние

- `scripts/build-deb.py` уже собирает .deb без root через dpkg-deb; версия читается из `pyproject.toml` (сейчас 0.2.3).
- origin: https://github.com/pavlenkoia/giga-pisar-dictation.git; workflow и теги отсутствуют.
- Автономные проверки и package smoke tests существуют; docs/development.md описывает команды.
- ADR 0003 исключал публичную публикацию из прежнего scope. Copyright сейчас сообщает personal use only / no license granted. Не считать этот план молчаливым изменением условий.

## Границы

Только release pipeline, его проверки и документация. Существующий layout .deb и runtime не менять. Не добавлять ARM, Wayland, APT repository, автообновление, signing, микрофонные/LAN/clipboard тесты. Не повышать версию ради добавления workflow. Не выполнять commit, push, отправку тегов или создание реального release без отдельной команды пользователя. Не менять локальную систему и её зависимости; apt-установка разрешается только в одноразовом GitHub runner.

## Решения для согласования

1. Автоматическая публикация обычного release по отправленному тегу `vX.Y.Z`, не по каждому push в main; ручной dispatch пока не нужен.
2. Runner Ubuntu 24.04 x86_64, пакет amd64; целевая ОС остаётся Mint 22.x Cinnamon/X11. Успешный CI не является desktop-приёмкой.
3. Версия тега, pyproject и metadata собранного пакета обязаны совпадать; несовпадение блокирует публикацию.
4. Публичная публикация владельцем разрешается как новый scope. Open-source лицензию не выбирать автоматически. Перед реализацией согласовать: сохранить отсутствие лицензии с уточнённым уведомлением о публичной доступности бинарника либо выбрать лицензию отдельной задачей. Не обещать пользователям разрешение на перераспространение/модификацию. Удаление ограничивающей фразы personal use only не выполнять без согласования текста.
5. Первый реальный выпуск и его версия согласуются отдельно после приёмки кода workflow.

## Затрагиваемые пути

- `.github/workflows/release.yml` — новый workflow.
- `scripts/check-release.py` — небольшой автономный валидатор тега/версии/пакета, если нужен для проверяемой логики вместо сложного inline shell.
- `tests/test_release.py` — автономные положительные/отрицательные проверки release validation.
- `docs/releases.md` — порядок выпуска, скачивания, установки и границы CI.
- `docs/README.md`, `docs/development.md`, `README.md` — ссылки и актуальные инструкции.
- `docs/decisions/0004-github-deb-releases.md` — новый ADR, явно расширяющий scope ADR 0003 без переписывания исторического решения.
- `packaging/deb/copyright`, `tests/test_packaging.py` — только если согласованный текст уведомления требует изменения; отсутствие лицензии сохраняется без отдельного выбора владельца.

## Шаги реализации

1. После одобрения и команды на исполнение передать встроенному worker со свежим контекстом этот план, AGENTS.md, актуальные docs и согласованный вариант публикации/уведомления. Модель брать из .pi/settings.json; подмену модели не делать.
2. Добавить validation строгого тега vX.Y.Z и совпадения с project version. Ошибочные теги, отсутствующая версия, неверный package version/architecture блокируют release. Проверять на временных фикстурах без изменения реальной версии проекта.
3. Создать workflow: trigger push tags; checkout точного tag commit с отключённым сохранением credentials; timeout; read-only permission по умолчанию. Закрепить внешние actions полными проверенными commit SHA.
4. Read-only build/test job на ubuntu-24.04: установить необходимые системные GI/GTK/Soup/GStreamer, D-Bus, X11 библиотеки и средства проверки только на runner. Использовать /usr/bin/python3, а не Python без system GI. Запустить полный unittest suite, compileall, CLI help, desktop-file-validate, сборку, dpkg metadata/contents и lintian. Два известных lintian warnings допустимы, новые ошибки не игнорировать. Не запускать обычный GUI launcher, настоящий capture, LAN или clipboard.
5. Проверить созданный пакет: единственный ожидаемый файл, имя/версия/amd64, содержимое и relocated launcher --help вне checkout без PYTHONPATH (существующий packaging test уже покрывает значительную часть). Сгенерировать SHA256SUMS с basename, приложить только ожидаемые .deb и checksum в Actions artifact для следующего job.
6. Отдельный publish job с needs build/test и contents: write получает только артефакт успешной сборки, без запуска кода приложения. Использовать встроенный GITHUB_TOKEN и gh CLI для создания Release. Добавить краткие release notes, целевую платформу, ограничения приёмки и лицензирования. Не перезаписывать уже опубликованные assets/release при повторном запуске; существующий release приводит к понятному отказу. Concurrency по тегу исключает конкурирующую публикацию; ошибки публикации не скрывать. Проверить digest/состав скачанного артефакта перед загрузкой.
7. Обновить docs и README: version update → проверки → commit/push по отдельной команде → tag/push по отдельной команде → проверка Release. Описать скачивание, sha256sum -c, установку через apt install ./package.deb пользователем, отсутствие APT автообновлений, GitHub Actions permissions и возможные policy блокеры. Не заявлять фактическую успешность cloud run до запуска.
8. Основной агент независимо проверяет diff, команды и результаты; затем свежий read-only reviewer проверяет план, docs, workflow permissions и diff. Подтверждённые замечания исправляет worker, проверки повторяются.

## Критерии готовности

- Корректный тег даёт один amd64 .deb и SHA256SUMS; неверный/несовпадающий тег не допускает публикации.
- Публикация зависит от всех обязательных тестов и package checks; privileged permission ограничен publish job.
- Нет пользовательских ключей, конфигов, аудио, транскриптов, доступа к целевой LAN/desktop или изменений локальной ОС.
- Нет незапрошенного bump версии, commit/push/tag или реального Release.
- Процесс выпуска и согласованные условия публичной доступности документированы; исторические решения не переопределены молча.
- Родительская проверка и fresh read-only review выполнены; cloud E2E либо подтверждён отдельно, либо явно отмечен непроверенным.

## Проверки

Локально, без установки зависимостей и desktop effects:

- `PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v`
- `/usr/bin/python3 -m compileall -q src tests scripts`
- `PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation --help`
- `/usr/bin/python3 scripts/build-deb.py`
- `dpkg-deb --info` / `--contents` для созданного пакета; распаковка/relocated launcher help во временном каталоге.
- `desktop-file-validate packaging/org.gigapisar.Dictation.desktop`
- `lintian` для созданного пакета (два известных warnings фиксировать честно).
- Регрессии release validator: корректный тег, mismatch, недопустимый формат, ошибочная архитектура/metadata; checksum verification.
- `git diff --check`; actionlint, если доступен без установки на рабочую систему. При отсутствии явно отметить, не заменять его простой YAML parsing как будто проверки эквивалентны.

После отдельного разрешения push/tag: проверить фактический Actions run, Release assets, скачивание и SHA256SUMS. Реальная установка и GTK/X11-приёмка — отдельный согласованный сценарий.

## Документация и риски

Обновление docs обязательно: это новая процедура публикации и расширение ранее принятого scope. GitHub policy/repository visibility, токен permissions и фактический cloud runner не подтверждены локальными проверками. Сборщик использует текущую дату в changelog, поэтому checksum относится к конкретному артефакту; bit-for-bit воспроизводимость между сборками не обещается. Установка в чистой Mint системе и полная desktop-приёмка остаются за рамками этой задачи.
