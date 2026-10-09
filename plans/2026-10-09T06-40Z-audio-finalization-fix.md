# Исправление финализации WAV

## Цель и контекст
Пользователь подтвердил точечное исправление записи после ошибки UI «Audio finalization failed». Вероятная причина подтверждается конфликтом читателей Gst.Bus: signal watch главного GLib loop конкурирует с timed_pop_filtered в stop worker thread. Реальный конкретный сбой ещё нужно воспроизвести без микрофона.

## Границы
Только audio lifecycle/финализация, минимальная необходимая интеграция desktop, тесты и документация. Copy/clipboard не менять. Один встроенный worker свежего контекста, модели из .pi/settings.json; parent независимые проверки и свежий read-only reviewer. Сохранить dirty/untracked прототип в feature/desktop-prototype. Без commit/push/установок/системных настроек/секретов/LAN/реального микрофона/clipboard/фокуса. Новое одобрение требуется при смене архитектуры или расширении границ.

## Пути и переиспользование
src/giga_pisar_dictation/audio.py, при необходимости desktop.py; tests/test_audio_lifecycle.py, отдельный локальный GStreamer regression; docs/development.md и manual-testing.md. Переиспользовать GstRecorder, injected gst/effect adapters, текущие generation guards, PrivateWav.

## Подход и шаги
- [ ] Worker воспроизводит конкуренцию на реальном GStreamer с audiotestsrc и приватным временным WAV, без подключения pulsesrc/микрофона и без отправки. GTK main loop моделировать GLib loop.
- [ ] Устранить два конкурирующих потребителя bus: согласованный единственный механизм получения EOS/ERROR с ограниченным ожиданием и синхронизацией отмены. Ошибки записи продолжают доставляться UI, stop/cancel идемпотентны, cleanup выполняется один раз, поздний completion не затрагивает следующую запись.
- [ ] Добавить регрессии EOS под активным GLib loop, ERROR/timeout/cancel во время финализации, повтор stop/cancel и очистку WAV. Реальный GStreamer synthetic test проверяет читаемый mono PCM16/16k WAV; пользовательские файлы не использовать.
- [ ] Запустить проверки, parent независимо изучает текущие изменения и запускает команды; fresh reviewer, исправление подтверждённых замечаний.
- [ ] Обновить docs фактическими результатами: synthetic GStreamer не равен реальной микрофонной или полной desktop-приёмке.

## Проверки и критерии
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 -m compileall -q src tests
PYTHONPATH=src /usr/bin/python3 -m giga_pisar_dictation --help
git diff --check

Финализация завершается EOS с корректным WAV при работающем GLib loop; timeout/ERROR/cancel не зависают и не оставляют audio pipeline/WAV; Copy без изменений. Реальный сценарий пользователя требует перезапуска приложения и отдельного подтверждения после исправления.
