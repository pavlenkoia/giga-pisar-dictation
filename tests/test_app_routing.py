import unittest

from giga_pisar_dictation.app import CommandApplication


class FakeCommandLine:
    def __init__(self, args, remote=False):
        self.args = ["giga-pisar-dictation", *args]
        self.remote = remote
        self.output = ""

    def get_arguments(self): return self.args
    def get_is_remote(self): return self.remote
    def print_literal(self, text): self.output += text


class LaunchRoutingTests(unittest.TestCase):
    def test_initial_ordinary_and_autostart_use_distinct_modes(self):
        launches = []
        router = CommandApplication.__new__(CommandApplication)
        router.on_launch = launches.append
        router.on_command = lambda command: self.fail(f"unexpected command: {command}")
        for args, expected in (([], "ordinary"), (["--autostart"], "autostart")):
            line = FakeCommandLine(args)
            self.assertEqual(router._command_line(None, line), 0)
            self.assertEqual(launches[-1], expected)
        self.assertEqual(launches, ["ordinary", "autostart"])

    def test_remote_ordinary_shows_and_repeated_autostart_is_noop(self):
        commands = []
        router = CommandApplication.__new__(CommandApplication)
        router.on_launch = lambda mode: self.fail(f"unexpected launch: {mode}")
        router.on_command = commands.append
        self.assertEqual(router._command_line(None, FakeCommandLine([], remote=True)), 0)
        self.assertEqual(commands, ["show"])
        self.assertEqual(router._command_line(None, FakeCommandLine(["--autostart"], remote=True)), 0)
        self.assertEqual(commands, ["show"])


if __name__ == "__main__": unittest.main()
