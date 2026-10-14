import unittest

from giga_pisar_dictation.desktop import DesktopEffects


class Status:
    def __init__(self):
        self.text = None

    def set_text(self, text):
        self.text = text


class FakeClient:
    def __init__(self, error=None):
        self.error = error
        self.called = False

    def health_async(self, callback):
        self.called = True
        callback({"status": "ok"} if self.error is None else None, self.error)


class DesktopHealthTests(unittest.TestCase):
    def effects(self, client):
        effects = DesktopEffects.__new__(DesktopEffects)
        effects.client = client
        effects.view = type("View", (), {"status": Status()})()
        return effects

    def test_health_success_has_same_status_for_http_and_https_clients(self):
        for scheme in ("http", "https"):
            with self.subTest(scheme=scheme):
                client = FakeClient()
                effects = self.effects(client)
                effects.config = type("Config", (), {"base_url": f"{scheme}://example.test"})()

                effects.health()

                self.assertTrue(client.called)
                self.assertEqual(effects.view.status.text, "Сервер доступен")

    def test_health_error_shows_error_for_http_and_https_clients(self):
        for scheme in ("http", "https"):
            with self.subTest(scheme=scheme):
                error = RuntimeError(f"{scheme} request failed")
                client = FakeClient(error)
                effects = self.effects(client)
                effects.config = type("Config", (), {"base_url": f"{scheme}://example.test"})()

                effects.health()

                self.assertTrue(client.called)
                self.assertEqual(effects.view.status.text, str(error))

    def test_health_without_client_prompts_for_key_without_http_warning(self):
        effects = self.effects(None)

        effects.health()

        self.assertEqual(effects.view.status.text, "Задайте ключ для проверки сервера")
        self.assertNotIn("HTTP", effects.view.status.text)


if __name__ == "__main__":
    unittest.main()
