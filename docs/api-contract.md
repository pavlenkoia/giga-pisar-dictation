# HTTP API контракт

Base URL (настраивается): `http://192.168.0.30:8737`.

- `GET /health` — асинхронная проверка, JSON object; авторизация Bearer.
- `POST /v1/audio/transcriptions` — multipart, одно поле `file`, WAV с фиксированным безопасным именем и известным размером; ответ JSON string `text`.
- Bearer только в `Authorization`; redirects не следуются. Ограничение тела ответа 64 KiB; ошибки/сырые тела не показываются пользователю.
- Различаются 401/403, 413, redirect, HTTP, невалидный JSON/text, пустой text, timeout, отмена и недоступность сети. Ошибки sanitised.
- HTTP не шифрует ключ/аудио; применять только на доверенной LAN. Серверные пределы размера/таймаутов не проверены.

Локальный `unittest` HTTP сервер с фиктивным ключом проверяет production Soup async поток, multipart, отмену, timeout, redirect, response cap и ошибки JSON/text. Реальный endpoint не проверялся этой реализацией.
