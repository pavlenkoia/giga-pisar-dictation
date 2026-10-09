"""Secure user configuration and API-key storage."""
from __future__ import annotations
import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_URL = "http://192.168.0.30:8737"
_PRIVATE = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = _PRIVATE | getattr(os, "O_DIRECTORY", 0)


@dataclass(frozen=True)
class Config:
    base_url: str = DEFAULT_URL
    timeout_seconds: int = 120
    audio_source: str = ""
    auto_insert: bool = True
    hotkey_enabled: bool = True
    hotkey_accelerator: str = "Ctrl+Space"

    def validate(self):
        parts = urlsplit(self.base_url)
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None or
                parts.password is not None or parts.query or parts.fragment): raise ValueError("Неверный базовый URL API")
        if not 1 <= self.timeout_seconds <= 3600: raise ValueError("Тайм-аут должен быть от 1 до 3600 секунд")
        if not isinstance(self.hotkey_enabled, bool): raise ValueError("Неверное значение настройки клавиши")
        if not isinstance(self.hotkey_accelerator, str): raise ValueError("Неверное сочетание клавиш")
        from .hotkey import parse_accelerator
        parse_accelerator(self.hotkey_accelerator)


def config_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "giga-pisar-dictation"


def _open_dir(path: Path, create=True):
    path = Path(os.path.abspath(path))
    fd = os.open("/", _DIRECTORY)
    try:
        for component in path.parts[1:]:
            try: next_fd = os.open(component, _DIRECTORY, dir_fd=fd)
            except FileNotFoundError:
                if not create: raise
                try: os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError: pass
                next_fd = os.open(component, _DIRECTORY, dir_fd=fd)
            os.close(fd); fd = next_fd
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or not stat.S_ISDIR(st.st_mode): raise PermissionError("Небезопасный каталог настроек")
        if stat.S_IMODE(st.st_mode) != 0o700: raise PermissionError("Права каталога настроек должны быть 0700")
        return fd
    except Exception:
        os.close(fd)
        raise


def _secure_dir(path):
    fd = _open_dir(path)
    os.close(fd)


def _read_private_at(directory_fd, name):
    fd = os.open(name, _PRIVATE, dir_fd=directory_fd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
            raise PermissionError("Небезопасный закрытый файл")
        chunks = []
        while True:
            data = os.read(fd, 65536)
            if not data: break
            chunks.append(data)
        return b"".join(chunks)
    finally: os.close(fd)


def load_config(directory=None):
    fd = _open_dir(directory or config_dir())
    try:
        try: data = _read_private_at(fd, "config.json")
        except FileNotFoundError: return Config()
        cfg = Config(**json.loads(data)); cfg.validate(); return cfg
    finally: os.close(fd)


def _atomic_write_at(directory_fd, name, data):
    try:
        old = os.open(name, _PRIVATE, dir_fd=directory_fd)
    except FileNotFoundError: old = None
    if old is not None:
        try:
            st = os.fstat(old)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
                raise PermissionError("Небезопасный существующий закрытый файл")
        finally: os.close(old)
    temp = f".write-{os.getpid()}-{os.urandom(8).hex()}"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.close(fd); fd = -1
        os.replace(temp, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        if fd >= 0: os.close(fd)
        try: os.unlink(temp, dir_fd=directory_fd)
        except FileNotFoundError: pass


def save_config(config, directory=None):
    config.validate(); fd = _open_dir(directory or config_dir())
    try: _atomic_write_at(fd, "config.json", json.dumps(asdict(config), indent=2).encode())
    finally: os.close(fd)


def save_api_key(key, directory=None):
    if not key or "\n" in key or "\r" in key: raise ValueError("Ключ API должен быть непустой строкой без переносов")
    fd = _open_dir(directory or config_dir())
    try: _atomic_write_at(fd, "api-key", key.encode("utf-8"))
    finally: os.close(fd)


def load_api_key(directory=None):
    fd = _open_dir(directory or config_dir())
    try:
        try: return _read_private_at(fd, "api-key").decode("utf-8")
        except FileNotFoundError: return ""
    finally: os.close(fd)
