# -*- coding: utf-8 -*-
"""
vijs_bridge.py — мост между Python-браузером ViBrow и нативным JS-движком
vijs_engine (Zig, папка vijs_engine/src в репозитории GitHub).

Зачем:
    Python-интерпретатор JavaScriptEngine (viengine_js.py) шагает по AST на
    чистом Python — на тяжёлых страницах (банки: React/webpack-бандлы) это
    "пиздец тормозит". Zig-движок компилирует выражения в байткод и выполняет
    их стековой VM с NaN-boxing (JsValue = u64), что на Raspberry Pi Zero
    быстрее на порядки.

Принципы:
    1. Движок используется ТОЛЬКО как быстрый предпрогон арифметических
       выражений (hot path). Всё остальное (DOM, fetch, Promise, события)
       остаётся на Python-движке — поведение не меняется.
    2. Если .so/.dll нет или Zig не установлен — мост молча деградирует до
       Python-движка. Браузер обязан работать в любом случае.
    3. Кэш результатов по нормализованному исходнику выражения: банковские
       бандлы повторяют одни и те же вычисления, второй прогон — O(1).

API:
    get_bridge() -> NativeJSBridge          (синглтон, потокобезопасный)
    bridge.is_native                        True если libvijs_engine загружена
    bridge.eval_arithmetic(src) -> float|None   None => нужен Python-движок
    build.sh / build.ps1                    сборка библиотек из src/*.zig
"""

import ctypes
import hashlib
import os
import platform
import re
import sys
import threading

ENGINE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vijs_engine")
NATIVE_DIR = os.path.join(ENGINE_ROOT, "native")
SRC_DIR = os.path.join(ENGINE_ROOT, "src")

# Память на вкладку должна совпадать с MAX_MEMORY_PER_TAB в engine.zig
MAX_MEMORY_PER_TAB = 20 * 1024 * 1024


def _library_name():
    system = platform.system()
    if system == "Windows":
        return "vijs_engine.dll"
    if system == "Darwin":
        return "libvijs_engine.dylib"
    return "libvijs_engine.so"


def _candidate_dirs():
    """Порядок поиска готовой библиотеки под текущую машину."""
    machine = platform.machine().lower()
    bits = "64" if sys.maxsize > 2**32 else "32"

    if machine in ("arm64", "aarch64"):
        arch_subdirs = ["linux_arm64", "macos_arm64", "windows_arm64", "linux_armv7"]
    elif machine in ("armv6l", "armv7l", "arm"):
        # Raspberry Pi Zero (1/W) — armv6, Zero 2 W — armv7/aarch64
        arch_subdirs = ["linux_armv6", "linux_armv7", "linux_arm64"]
    elif machine in ("amd64", "x86_64", "i686", "i386"):
        if system_is_win := platform.system() == "Windows":
            arch_subdirs = ["windows_x64"] if bits == "64" else ["windows_x64"]
        elif platform.system() == "Darwin":
            arch_subdirs = ["macos_x64", "macos_arm64"]
        else:
            arch_subdirs = ["linux_x64"]
    else:
        arch_subdirs = ["linux_x64", "linux_arm64", "linux_armv7", "linux_armv6"]

    dirs = [os.path.join(NATIVE_DIR, sub) for sub in arch_subdirs]
    dirs.append(NATIVE_DIR)  # если пользователь положил .so просто в native/
    env_dir = os.environ.get("VIJS_ENGINE_DIR")
    if env_dir:
        dirs.insert(0, env_dir)
    return dirs


# ─────────────────────────────────────────────────────────────
# Быстрая проверка: годится ли исходник для нативного движка?
# ─────────────────────────────────────────────────────────────

# Нативный движок умеет числа, + - * / % ** ( ), унарные +/-, комментарии.
_ALLOWED_CHARS = set("0123456789+-*/%().eE \t\r\n")
_FULLNUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NUMBERISH_RE = _FULLNUM_RE
_HEX_RE = re.compile(r"0[xX][0-9a-fA-F]+")
_LEAKY_RE = re.compile(r"[a-zA-Z_$][\w$]*")  # идентификаторы => не чистая арифметика


def _normalize_expression(src):
    """Ключ кэша: убираем пробелы, приводим числа к каноническому виду."""
    parts = []
    i = 0
    s = src.strip()
    while i < len(s):
        m = _NUMBERISH_RE.match(s, i) or _HEX_RE.match(s, i)
        if m:
            try:
                parts.append(repr(float(m.group(0))))
            except ValueError:
                return None
            i = m.end()
            continue
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        parts.append(ch)
        i += 1
    return "".join(parts)


class NativeJSBridge:
    """ctypes-обёртка над libvijs_engine.so / .dll / .dylib."""

    def __init__(self):
        self._lock = threading.Lock()
        self._lib = None
        self._cache = {}
        self._cache_key_limit = 4096
        self.status = ""
        self.library_path = None
        self._load()

    # ── загрузка ────────────────────────────────────────────
    def _load(self):
        name = _library_name()
        for directory in _candidate_dirs():
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            try:
                lib = ctypes.CDLL(path)
            except OSError as exc:
                self.status = f"не удалось загрузить {path}: {exc}"
                continue
            try:
                lib.vijs_execute.argtypes = [ctypes.c_char_p]
                lib.vijs_execute.restype = ctypes.c_double
                lib.vijs_is_number.argtypes = [ctypes.c_char_p]
                lib.vijs_is_number.restype = ctypes.c_bool
                lib.vijs_get_type.argtypes = [ctypes.c_char_p]
                lib.vijs_get_type.restype = ctypes.c_uint8
            except AttributeError:
                self.status = f"в {path} нет экспорта vijs_* — нужна сборка из vijs_engine/src"
                continue
            self._lib = lib
            self.library_path = path
            self.status = f"нативный движок загружен: {path}"
            return
        if not self.status:
            self.status = (
                "нативная библиотека не найдена — работаем на Python-движке "
                f"(соберите её: cd vijs_engine && ./build.sh)"
            )

    @property
    def is_native(self):
        return self._lib is not None

    # ── выполнение ──────────────────────────────────────────
    def supports(self, source):
        """True если source — чистое арифметическое выражение без идентификаторов."""
        if not source or len(source) > 512:
            return False
        s = source.strip().rstrip(";").strip()
        if not s or s.startswith(("//", "/*")):
            return False
        # Заменяем числа целиком (включая экспоненту 1e-9), чтобы буква 'e'
        # не осталась в "очистке" и не была ошибочно принята за мусор.
        cleaned = _FULLNUM_RE.sub("#", s)
        cleaned = _HEX_RE.sub("#", cleaned)
        if _LEAKY_RE.search(cleaned):
            return False
        return all(ch in _ALLOWED_CHARS or ch == "#" for ch in cleaned) and "#" in cleaned

    def eval_arithmetic(self, source):
        """Вычисляет арифметическое выражение нативным движком.

        Возвращает float либо None (выражение не поддерживается / ошибка —
        вызывающий должен упасть обратно на Python-движок).
        """
        if self._lib is None:
            return None
        if not self.supports(source):
            return None
        key = _normalize_expression(source)
        if key is None:
            return None
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        payload = source.encode("utf-8", "ignore") + b"\x00"
        try:
            with self._lock:
                ok = bool(self._lib.vijs_is_number(payload))
                result = self._lib.vijs_execute(payload) if ok else None
        except Exception:
            return None
        if result is None or result != result:  # NaN => ошибка движка
            return None
        if len(self._cache) >= self._cache_key_limit:
            self._cache.clear()
        self._cache[key] = result
        return result

    # ── диагностика ─────────────────────────────────────────
    def info(self):
        return {
            "native": self.is_native,
            "library": self.library_path,
            "status": self.status,
            "cache_size": len(self._cache),
        }


_BRIDGE = None
_BRIDGE_LOCK = threading.Lock()


def get_bridge():
    """Синглтон моста (ленивая загрузка библиотеки)."""
    global _BRIDGE
    if _BRIDGE is None:
        with _BRIDGE_LOCK:
            if _BRIDGE is None:
                _BRIDGE = NativeJSBridge()
    return _BRIDGE
