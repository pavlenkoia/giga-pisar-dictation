"""Safely manage only this user's application-owned XDG autostart entry."""
from __future__ import annotations
import os
import secrets
import stat
from pathlib import Path

APP_ID = "org.gigapisar.Dictation"
DESKTOP_CONTENT = b"[Desktop Entry]\nType=Application\nName=Giga Pisar Dictation\nExec=/usr/bin/giga-pisar-dictation --autostart\nTerminal=false\nX-GNOME-Autostart-enabled=true\n"
_NAME = APP_ID + ".desktop"
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) |
               getattr(os, "O_NONBLOCK", 0))


def _directory_fd(path: Path, *, create=False):
    path = Path(os.path.abspath(path))
    fd = os.open("/", _DIR_FLAGS)
    try:
        for index, component in enumerate(path.parts[1:]):
            final = index == len(path.parts[1:]) - 1
            try:
                child = os.open(component, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not (create and final): raise
                os.mkdir(component, 0o755, dir_fd=fd)
                child = os.open(component, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        metadata = os.fstat(fd)
        if metadata.st_uid != os.getuid() or not stat.S_ISDIR(metadata.st_mode):
            raise PermissionError("Unsafe autostart directory")
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise PermissionError("Autostart directory is writable by other users")
        return fd
    except Exception:
        os.close(fd)
        raise


class AutostartFile:
    def __init__(self, config_home=None):
        self.config_home = Path(config_home or os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        if not self.config_home.is_absolute():
            raise ValueError("XDG_CONFIG_HOME must be absolute")
        self.directory = self.config_home / "autostart"

    def _open_directory(self, create=False):
        return _directory_fd(self.directory, create=create)

    @staticmethod
    def _read_owned(fd):
        try: file_fd = os.open(_NAME, _FILE_FLAGS, dir_fd=fd)
        except FileNotFoundError: return None
        try:
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise PermissionError("Autostart entry is not an owned regular file")
            if stat.S_IMODE(metadata.st_mode) & 0o022:
                raise PermissionError("Autostart entry is writable by other users")
            content = os.read(file_fd, len(DESKTOP_CONTENT) + 1)
            if len(content) > len(DESKTOP_CONTENT):
                raise PermissionError("Autostart entry is too large to be application-owned")
            if content != DESKTOP_CONTENT:
                raise PermissionError("Refusing to alter an unrecognized autostart entry")
            return content
        finally:
            os.close(file_fd)

    def is_enabled(self):
        try: fd = self._open_directory()
        except FileNotFoundError: return False
        try: return self._read_owned(fd) == DESKTOP_CONTENT
        finally: os.close(fd)

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if not enabled:
            try: fd = self._open_directory()
            except FileNotFoundError: return
            try:
                if self._read_owned(fd) is not None:
                    os.unlink(_NAME, dir_fd=fd)
                    os.fsync(fd)
            finally: os.close(fd)
            return

        fd = self._open_directory(create=True)
        temp_name = "." + _NAME + "." + secrets.token_hex(8)
        try:
            existing = self._read_owned(fd)
            if existing == DESKTOP_CONTENT: return
            temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                              0o644, dir_fd=fd)
            try:
                with os.fdopen(temp_fd, "wb", closefd=False) as output:
                    output.write(DESKTOP_CONTENT); output.flush(); os.fsync(output.fileno())
                os.close(temp_fd); temp_fd = -1
                os.replace(temp_name, _NAME, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                if temp_fd >= 0: os.close(temp_fd)
                try: os.unlink(temp_name, dir_fd=fd)
                except FileNotFoundError: pass
        finally: os.close(fd)
