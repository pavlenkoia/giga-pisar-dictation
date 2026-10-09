# Giga Pisar Dictation

GTK3/X11 client prototype for dictation to a user-managed Giga Pisar server on a trusted LAN. Requires system Python GI bindings for GTK 3, Gio, Soup 3, and GStreamer 1.0 plus the GStreamer PulseAudio source, WAV encoder, and X11/XTest libraries. No install or service configuration is performed by this repository.

Run from the checkout:

```sh
PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation
```

The desktop window asks for the API base URL and key in Settings; the key is stored separately in a user config directory with mode 0600. The default endpoint uses plain HTTP and is safe only on a trusted LAN. Use Cinnamon's keyboard-shortcut settings to assign a command manually; see [manual testing](docs/manual-testing.md). The app does not register a global shortcut or change Cinnamon settings.

Commands `start`, `stop`, `cancel`, `status`, and `toggle` route over the user's Gio session bus to an existing desktop instance. With no running instance, commands refuse rather than silently recording. `status` excludes key and transcription content.

Autonomous tests use adapters, fictional credentials, a local HTTP server, and a disposable D-Bus session. They do not use a microphone or mutate a real clipboard:

```sh
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q src tests
PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation --help
git diff --check
```

This prototype has not been accepted through the target Cinnamon/X11 desktop and LAN scenario. See [docs](docs/README.md) for constraints and status.
