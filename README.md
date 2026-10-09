# Гига Писарь

Русский клиент диктовки для рабочего стола GTK3/X11, работающий с сервером Giga Pisar в доверенной локальной сети. Первый установочный пакет `.deb` предназначен для Linux Mint 22.x x86_64/Cinnamon/X11; другие дистрибутивы и Wayland отдельно не проверялись. Системные зависимости GI, GTK, GStreamer и X11 указаны в пакете. Пакет не настраивает сервер, ключ, микрофон, системные сочетания клавиш или службы.

Run from the checkout:

```sh
PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation
```

On first launch without an API key, the window opens **Настройки**. The key is stored separately in a user config directory with mode 0600. The default endpoint uses plain HTTP and is safe only on a trusted LAN. The app registers Ctrl+Space globally on X11 by default; change or disable it in **Настройки**. It does not change Cinnamon settings. Login autostart is opt-in and managed only through the app-owned XDG desktop entry. See [manual testing](docs/manual-testing.md).

Build an unprivileged Mint-targeted package with `/usr/bin/python3 scripts/build-deb.py`; it writes `dist/giga-pisar-dictation_0.2.2_amd64.deb`. The installed launcher and menu entry do not require a checkout. Ordinary repeated launch shows the existing window; explicit `start`, `stop`, `cancel`, `status`, and `toggle` commands route over Gio session-bus IPC. With no running instance, commands refuse rather than silently recording. `status` excludes key and transcription content.

Autonomous tests use adapters, fictional credentials, a local HTTP server, and a disposable D-Bus session. They do not use a microphone or mutate a real clipboard:

```sh
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q src tests
PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation --help
git diff --check
```

The `.deb` has been built and checked without installing it. Owner-published binary downloads may be offered in GitHub Releases; no license is granted and download availability grants no redistribution or reuse permission. See [release instructions](docs/releases.md). Full Mint/Cinnamon/X11, tray-host, autostart-login, update/removal and LAN acceptance remains unperformed. AppIndicator hosts may show a menu on ordinary left click; **Показать окно** remains available from the menu and by launching the app. See [docs](docs/README.md) for constraints and measured results.
