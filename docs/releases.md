# Выпуск Debian-пакетов

После отправки тега `vX.Y.Z` GitHub Actions проверяет отмеченный коммит, собирает один пакет `.deb` для amd64 и публикует его вместе с `SHA256SUMS` в GitHub Releases. Версия в `pyproject.toml`, метаданные пакета и тег должны совпадать.

Если выпуск с таким тегом уже существует, публикация останавливается без перезаписи. Для исправленного пакета нужна новая версия и новый тег.

## Выпуск v0.2.10

[Выпуск v0.2.10](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.10) опубликован с commit `ea17c5e`: в режиме «Рация» суммарное удержание правого Ctrl меньше 700 мс отменяет запись без отправки и ошибки; хвост 300 мс и паузы не учитываются. Повторные удержания одной записи суммируются целыми наносекундами. [GitHub Actions 38535357919](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/38535357919): build-and-test и publish — success. Опубликованные `.deb` и `SHA256SUMS` скачаны; checksum и strict release validator прошли. SHA256 `.deb`: `1668d2808c18e9e7c5206699fb697b6e46034756dcea8c6d64c0cdc3a1c2bc55`. Локально независимо прошли 175 тестов, compileall, CLI help, desktop-file validation, strict package validator, lintian policy, extracted launcher help и checksum. Финальные review реализации и release-метаданных — OK. Реальная GTK/X11-приёмка и установка не выполнялись. CI сообщил известное предупреждение о Node.js 20 в закреплённых actions; исполнение шло на Node.js 24.

## Выпуск v0.2.9

[Выпуск v0.2.9](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.9) опубликован с commit `894b901`: нерелевантные MappingNotify больше не сбрасывают обработчик правого Ctrl; сохранены инвалидация при ошибке mapping, восстановление binding и защита prepared candidate при смене mapping туда/обратно. [GitHub Actions 38435175707](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/38435175707): build-and-test и publish — success. `.deb` и `SHA256SUMS` скачаны; checksum и strict release validator прошли. SHA256 `.deb`: `2404cf38d4fad69799b659a36486b545791384022884b75db5b972844b647c44`. Локально независимо прошли 169 тестов, compileall, CLI help, desktop-file validation, сборка, lintian policy, extracted launcher help и checksum. Финальный review реализации и release-метаданных — OK. Связь исправленного fake-дефекта с пропуском после живой вставки не подтверждена; GTK/X11-приёмка и установка не выполнялись. CI сообщил известное предупреждение о Node.js 20 в закреплённых actions; выполнение шло на Node.js 24.

## Выпуск v0.2.8

[Выпуск v0.2.8](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.8) опубликован с commit `28478b8`: режим «Рация» оставляет 300 мс захвата после отпускания правого Ctrl; повторное нажатие в этом интервале продолжает ту же запись, а смена mapping/закрытие binding отменяют хвост. [GitHub Actions 38431108643](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/38431108643): build-and-test и publish — success. `.deb` и `SHA256SUMS` скачаны; checksum и strict release validator прошли. SHA256 `.deb`: `937167948a2ddabb61a496124fc81b60d9d24291ee2180b481f4d6aa8f938777`. Локально прошли 161 тест, compileall, CLI help, desktop-file validation, сборка пакета, lintian policy, extracted launcher help и checksum; review — OK. Причина пропуска первого нажатия правого Ctrl не установлена. Реальная GTK/X11-приёмка не выполнялась, пакет агентом не устанавливался. CI сообщил предупреждение о Node.js 20 в закреплённых actions; запуск выполнялся на Node.js 24.

## Выпуск v0.2.7

[Выпуск v0.2.7](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.7) опубликован с commit `365c44b`: к непустому тексту автоматической вставки дописывается один завершающий пробел; ручное Copy остаётся точным. [GitHub Actions 38425848725](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/38425848725): build-and-test и publish — success. `.deb` и `SHA256SUMS` скачаны; SHA256 и strict release validator прошли. Локально прошли 155 тестов, compileall, CLI help, desktop-file validation, сборка пакета, lintian policy, extracted launcher help и проверка checksum. Review — OK. Реальная GTK/X11-приёмка не выполнялась, пакет агентом не устанавливался. CI показал известное предупреждение о Node.js 20 в закреплённых actions, исполнение шло на Node.js 24.

## Выпуск v0.2.6

[Выпуск v0.2.6](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.6) опубликован с commit `601ed30`: добавлен отдельный режим «Рация — правый Ctrl» (ADR 0006), прежний toggle сохранён. [GitHub Actions 38417958129](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/38417958129): build-and-test и publish — success. Опубликованные `.deb` и `SHA256SUMS` скачаны и независимо проверены по SHA256 и strict release validator. Локально прошли 153 теста, compileall, проверки пакета, extracted launcher help, desktop-file validation и lintian policy; независимые review реализации и release-метаданных — без дефектов. Реальная Cinnamon/GTK/X11-приёмка не выполнялась, пакет агентом не устанавливался. CI сообщил прежнее неблокирующее предупреждение о Node.js 20 в закреплённых действиях; исполнение шло на Node.js 24.

## Выпуск v0.2.5

[Выпуск v0.2.5](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.5) опубликован с commit `650f328`: убрана ошибочная блокировка автозапуска из-за group/other-write у принадлежащего пользователю каталога, включая 0775; права каталога не меняются. [GitHub Actions 38293233382](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/38293233382): build-and-test и publish — success. `.deb` и `SHA256SUMS` скачаны и независимо проверены по SHA256 и strict release validator. Локально прошли 135 тестов, compileall, проверки пакета и lintian policy; независимый review — OK. Реальная GTK/X11-приёмка и login autostart не выполнялись, пакет агентом не устанавливался.

## Выпуск v0.2.4

[Выпуск v0.2.4](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.4) опубликован с commit `39f082c`: автоматическая вставка через XTest Ctrl+V и best-effort восстановление прежнего текста или изображения clipboard (ADR 0005). Пользователь подтвердил быструю базовую работу. [GitHub Actions 38235798087](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/38235798087): build-and-test и publish — success. `.deb` и `SHA256SUMS` скачаны и независимо проверены по SHA256 и strict release validator. Локально: 133 теста, compileall, сборка, strict package validator, desktop-file-validate, extracted launcher help и lintian policy прошли. Полная desktop-приёмка не выполнялась; пакет агентом не устанавливался.

## Подтверждённый выпуск

Первый публичный [выпуск v0.2.3](https://github.com/pavlenkoia/giga-pisar-dictation/releases/tag/v0.2.3) опубликован по разрешению владельца. В [запуске GitHub Actions 37937954360](https://github.com/pavlenkoia/giga-pisar-dictation/actions/runs/37937954360) успешно завершились сборка, 133 теста, проверки пакета и публикация.

Оба файла скачаны из опубликованного выпуска; контрольная сумма и метаданные пакета проверены независимо. Изменения автоматического выпуска влиты в `main`. Тег `v0.2.3` по-прежнему указывает на коммит сборки `90eba85` и не перемещался.

Этот запуск подтверждает работу настроек репозитория и разрешений токена на момент выпуска, но не гарантирует будущие запуски или работу приложения в графической сессии. GitHub сообщил неблокирующее предупреждение об устаревшем Node.js 20 в закреплённых действиях; среда сборки использовала Node.js 24. Обновление этих действий остаётся отдельной задачей.

## Порядок выпуска для сопровождающего

1. Обновите версию в `pyproject.toml` и описание изменений пакета в `scripts/build-deb.py`. Выполните тесты и проверки из [документа о разработке](development.md).
2. Проверьте изменения, создайте коммит и отправьте его в репозиторий. При работе через агента операции Git выполняются только по отдельному разрешению владельца. Автоматическая сборка не повышает версию сама.
3. Создайте и отправьте совпадающий тег `vX.Y.Z`. Его отправка запускает сборку и публикацию — это не только отметка версии. При работе через агента требуется отдельное разрешение на этот шаг.
4. Проверьте оба задания GitHub Actions: сборку с тестами и публикацию.
5. Убедитесь, что в выпуске есть `.deb` и `SHA256SUMS`, скачайте оба файла и проверьте контрольную сумму из каталога скачивания:

   ```sh
   sha256sum --check --strict SHA256SUMS
   ```

Не перемещайте опубликованный тег и не заменяйте файлы уже выпущенной версии.

## Как устроена автоматизация

Сценарий находится в [`.github/workflows/release.yml`](../.github/workflows/release.yml).

- Сборка и тесты работают с правом чтения репозитория на Ubuntu 24.04, x86_64.
- Проверяются формат тега, версия проекта, имя и метаданные пакета, содержимое и запуск распакованной справки. Проверка `lintian` допускает только два известных предупреждения: отсутствие указания правообладателя и страницы руководства.
- Отдельное задание публикации получает право `contents: write` и встроенный `GITHUB_TOKEN`; дополнительный личный токен не нужен.
- Задание публикации не загружает исходники и не выполняет скрипты репозитория. Оно проверяет скачанные файлы и контрольную сумму, наличие тега и отсутствие существующего выпуска, затем обращается к API через GitHub CLI.
- Сторонние действия закреплены полными идентификаторами коммитов. Повторная публикация существующего выпуска запрещена.

## Скачать и установить

Скачайте пакет и `SHA256SUMS` из [GitHub Releases](https://github.com/pavlenkoia/giga-pisar-dictation/releases) в один каталог. Для выпуска 0.2.10:

```sh
sha256sum --check --strict SHA256SUMS
sudo apt install ./giga-pisar-dictation_0.2.10_amd64.deb
```

Устанавливайте пакет только после успешной проверки. Репозитория APT и автоматических обновлений нет: новые версии нужно скачивать и устанавливать вручную.

Целевая платформа остаётся Linux Mint 22.x/Cinnamon/X11, x86_64. Проверки на Ubuntu 24.04 не заменяют испытание в целевой графической сессии. Первый запуск и ограничения описаны в [основном README](../README.md).

## Условия распространения

Владелец разрешил публикацию бинарного пакета для скачивания. Лицензия на проект не предоставлена; публичная доступность не даёт разрешения на перераспространение или повторное использование. Лицензия с открытым исходным кодом не выбрана.

Публикация в GitHub Releases не меняет устройство пакета, поведение приложения или необходимость отдельной проверки графического интерфейса и работы с сервером в локальной сети.
