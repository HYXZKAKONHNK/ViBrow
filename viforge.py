# -*- coding: utf-8 -*-
"""
ViForge — аналог Electron на базе движка viengine (ViBrow).

Возможности:
  * Мастер настройки: выбор целевой ОС, оконного менеджера, режима окна,
    размеров, темы, шрифтов, GPU-ускорения, кэша, прокси и т.д.
  * Редактор кода с подсветкой синтаксиса (HTML / CSS / JS / Python),
    нумерацией строк, автодополнением по ключевым словам, поиском/заменой.
  * Ввод URL + загрузка страниц через requests (как в viengine).
  * Встроенный JS-движок (viengine_js) и DOM-парсер (viengine_dom):
    скрипты на странице реально исполняются, есть console.log/alert/prompt.
  * Консоль DevTools: логи engine / js / python, счётчики ошибок.
  * Мост window.viElectron (аналог ipcRenderer): toast, setTitle, close,
    getWindowConfig, getPlatform, log, setInterval/setTimeout.
  * Hot Reload (Ctrl+R), сохранение проекта (main.html + package.json),
    запуск "продакшн-сборки" (python app.py --production).
  * Готовый main.py для экспортированного приложения запускается
    автономно, переиспользуя модули viengine из этого каталога.

Запуск:  python viforge.py
Только стандартная библиотека + то же, что использует viengine (requests).
"""

import json
import platform
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Интеграция с настоящим движком viengine (если он рядом) -------------------
try:
    from viengine_dom import Document, parse_html  # noqa
    from viengine_js import JavaScriptEngine  # noqa
    HAVE_VIENGINE = True
except Exception:  # pragma: no cover - движок обязателен, но не ломаем UI
    HAVE_VIENGINE = False

try:
    import requests
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False


APP_TITLE = "ViElectron — аналог Electron на viengine"
VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Справочники для мастера настройки ("дохуя всего")
# ---------------------------------------------------------------------------

OS_TARGETS = {
    "Windows 11": {"platform": "win32", "default_wm": "DWM"},
    "Windows 10": {"platform": "win32", "default_wm": "DWM"},
    "Linux": {"platform": "linux", "default_wm": "Mutter (GNOME)"},
    "macOS": {"platform": "darwin", "default_wm": "Quartz Compositor"},
    "Android": {"platform": "android", "default_wm": "SurfaceFlinger"},
    "Raspberry Pi OS": {"platform": "linux", "default_wm": "Mutter (GNOME)"},
    "Cross-platform": {"platform": "any", "default_wm": "Авто"},
}

WINDOW_MANAGERS = {
    "win32": ["DWM (Desktop Window Manager)", "Авто"],
    "linux": [
        "Mutter (GNOME)", "KWin (KDE Plasma)", "Wayland/Weston", "Xfwm4 (XFCE)",
        "Marco (MATE)", "Openbox", "i3 / Sway (tiling)", "Hyprland", "AwesomeWM",
        "bspwm", "Auto (определить)",
    ],
    "darwin": ["Quartz Compositor", "Авто"],
    "android": ["SurfaceFlinger", "Авто"],
    "any": ["Авто (определить при запуске)"],
}

THEMES = {
    "dark":   {"bg": "#1e1f22", "fg": "#e6e6e6", "content_bg": "#14151a",
               "content_fg": "#dcdcdc", "accent": "#7aa2f7", "panel": "#26272b"},
    "light":  {"bg": "#eef1f5", "fg": "#1f2328", "content_bg": "#ffffff",
               "content_fg": "#202124", "accent": "#2563eb", "panel": "#dde3ea"},
    "dracula":    {"bg": "#282a36", "fg": "#f8f8f2", "content_bg": "#21222c",
                   "content_fg": "#f8f8f2", "accent": "#bd93f9", "panel": "#343746"},
    "monokai":    {"bg": "#272822", "fg": "#f9f8f5", "content_bg": "#1f201b",
                   "content_fg": "#f9f8f5", "accent": "#fd971f", "panel": "#33342c"},
    "solarized":  {"bg": "#002b36", "fg": "#93a1a1", "content_bg": "#073642",
                   "content_fg": "#eee8d5", "accent": "#268bd2", "panel": "#0a3a48"},
    "nord":       {"bg": "#2e3440", "fg": "#d8dee9", "content_bg": "#3b4252",
                   "content_fg": "#eceff4", "accent": "#88c0d0", "panel": "#434c5e"},
}

FONT_FAMILIES = sorted({
    "Arial", "Consolas", "Courier New", "DejaVu Sans Mono", "JetBrains Mono",
    "Fira Code", "Cascadia Code", "Segoe UI", "Times New Roman", "Verdana",
    "SF Mono", "Monaco", "Liberation Mono",
})

SYNTAX_STYLES = {
    "html": [
        (r"(?s)<!--.*?-->", "#6a9955"),
        (r"</?[a-zA-Z][\w:-]*", "#569cd6"),
        (r"[a-zA-Z-]+(?==)", "#9cdcfe"),
        (r'"[^"]*"', "#ce9178"),
        (r"'[^']*'", "#ce9178"),
    ],
    "css": [
        (r"/\*.*?\*/", "#6a9955"),
        (r"[.#][\w-]+", "#d7ba7d"),
        (r"#[0-9a-fA-F]{3,8}\b", "#ce9178"),
        (r"[\w-]+(?=\s*:)", "#9cdcfe"),
        (r"[{};:]", "#808080"),
    ],
    "javascript": [
        (r"//[^\n]*", "#6a9955"),
        (r"(?s)/\*.*?\*/", "#6a9955"),
        (r"(?<![\w.])(?:var|let|const|function|return|if|else|for|while|do|"
         r"break|continue|new|class|extends|this|typeof|instanceof|in|of|"
         r"try|catch|finally|throw|null|undefined|true|false)(?![\w.])", "#c586c0"),
        (r"(?<![\w.])(?:document|window|console|Math|JSON|Object|Array|String|"
         r"Number|Boolean|Date|setTimeout|setInterval)(?![\w.])", "#4fc1ff"),
        (r"\b\d+(?:\.\d+)?\b", "#b5cea8"),
        (r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"", "#ce9178"),
    ],
    "python": [
        (r"#[^\n]*", "#6a9955"),
        (r"(?m)(?:^|\s)(def|class|return|if|elif|else|for|while|break|continue|"
         r"import|from|as|pass|lambda|yield|try|except|finally|raise|with|in|is|"
         r"not|and|or|None|True|False|self)(?![\w])", "#c586c0"),
        (r"(?<![\w.])print(?=\s*\()", "#dcdcaa"),
        (r"\b\d+(?:\.\d+)?\b", "#b5cea8"),
        (r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"", "#ce9178"),
    ],
}

DEFAULT_MAIN_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Мое ViElectron приложение</title>
  <style>
    body { background: #14151a; color: #e6e6e6; font-family: Arial; text-align: center; }
    .card { background: #1e1f22; border-radius: 12px; padding: 24px; margin: 40px auto; width: 420px; }
    button { background: #7aa2f7; color: #14151a; border: none; padding: 10px 18px;
             border-radius: 8px; font-size: 15px; cursor: pointer; }
    h1 { color: #9ece6a; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Привет, ViElectron!</h1>
    <p id="counter">Кликов: 0</p>
    <button onclick="bump()">Кликни меня</button>
    <button onclick="sayHi()">Toast</button>
  </div>
  <script>
    let n = 0;
    function bump() {
      n += 1;
      document.getElementById("counter").textContent = "Кликов: " + n;
      console.log("клик номер " + n);
    }
    function sayHi() {
      window.viElectron.toast("Работает! Платформа: " + window.viElectron.getPlatform());
      window.viElectron.setTitle("Кликов: " + n);
    }
    window.viElectron.log("Страница загружена, config: " +
      JSON.stringify(window.viElectron.getWindowConfig()));
  </script>
</body>
</html>
"""

DEFAULT_APP_PY = '''#!/usr/bin/env python3
"""Собранное ViElectron приложение (аналог electron .)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # каталог с модулями viengine

from viforge import ViElectronApp, load_project  # noqa: E402

config, html_source = load_project(HERE)
app = ViElectronApp(config=config, start_html=html_source, production=True)
app.run()
'''


def detect_platform():
    p = sys.platform
    if p.startswith("win"):
        return "win32"
    if p == "darwin":
        return "darwin"
    if p.startswith("linux"):
        return "linux"
    return "any"


def detect_window_manager():
    plat = detect_platform()
    if plat == "win32":
        return "DWM (Desktop Window Manager)"
    if plat == "darwin":
        return "Quartz Compositor"
    de = None
    for var in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "WAYLAND_DISPLAY"):
        import os
        v = os.environ.get(var)
        if v:
            de = v
            break
    return de or "Неизвестный WM (авто)"


# ---------------------------------------------------------------------------
# Мини-интерпретатор JS для fallback-режима (когда viengine_js недоступен)
# ---------------------------------------------------------------------------

class MiniJS:
    """Строчный мини-движок для onclick и <script>, когда viengine_js рядом нет.

    Поддерживает: присваивания let/var/const, вызовы document/console/window,
    строковые литералы, числа, конкатенацию. Затычка, чтобы UI жил без движка.
    """

    def __init__(self, host):
        self.host = host
        self.vars = {}

    def run_script(self, code):
        for line in code.splitlines():
            line = line.strip().rstrip(";")
            if not line or line.startswith("//"):
                continue
            line = re.sub(r"^(var|let|const)\s+", "", line)
            m = re.match(r"^([A-Za-z_$][\w$]*)\s*=\s*(.+)$", line)
            if m:
                name, expr = m.group(1), m.group(2)
            else:
                name, expr = None, line
            try:
                value = self.eval_expr(expr)
                if name:
                    self.vars[name] = value
            except Exception as e:
                self.host.log("js", "mini-JS ошибка в %r: %s" % (line, e))

    def eval_expr(self, expr, extra_vars=None):
        env = dict(self.vars)
        if extra_vars:
            env.update(extra_vars)
        safe_globals = {
            "__builtins__": {},
            "document": self.host.dom_api,
            "console": self.host.console_api,
            "window": self.host.window_api,
            "JSON": _JsonStub,
        }
        safe_globals.update(env)
        return eval(expr, safe_globals)  # noqa: S307 — закрытое окружение


class _JsonStub:
    @staticmethod
    def stringify(obj):
        return json.dumps(obj, ensure_ascii=False, default=str)

    @staticmethod
    def parse(text):
        return json.loads(text)


# ---------------------------------------------------------------------------
# Браузерное ядро приложения: рендер HTML/CSS, исполнение JS, мост
# ---------------------------------------------------------------------------

class ContentFrame(tk.Frame):
    """Контейнер страницы со скроллом (аналог <webview>/BrowserWindow)."""

    def __init__(self, master, app):
        super().__init__(master, bg=app.theme["content_bg"])
        self.app = app
        self.canvas = tk.Canvas(self, bg=app.theme["content_bg"],
                                highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=app.theme["content_bg"])
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner,
                                                  anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel)
        self.canvas.bind_all("<Button-5>", self._on_wheel)

    def _on_wheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta == 0:
            delta = -120 if event.num == 5 else 120
        self.canvas.yview_scroll(int(-delta / 60), "units")

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()

    def apply_theme(self):
        th = self.app.theme
        self.configure(bg=th["content_bg"])
        self.canvas.configure(bg=th["content_bg"])
        self.inner.configure(bg=th["content_bg"])


class ViElectronApp:
    """Каркас аналога Electron: окно + контент + devtools + мост."""

    def __init__(self, config=None, start_html=None, url=None, production=False):
        self.config = config or self.default_config()
        self.production = production
        self.start_html = start_html if start_html is not None else DEFAULT_MAIN_HTML
        self.start_url = url
        self.root = tk.Tk()
        self.root.title(self.config["window"]["title"])
        self.msg_queue = queue.Queue()
        self.js_engine = None
        self.page_document = None
        self._build_ui()
        self._bind_keys()
        if url:
            self.root.after(300, lambda: self.load_url(url))
        else:
            self.render_html(self.start_html)

    # --------------------------------------------------------------- config
    @staticmethod
    def default_config():
        return {
            "name": "vi-electron-app",
            "version": VERSION,
            "os_target": "Cross-platform",
            "window_manager": "Авто (определить при запуске)",
            "window": {
                "width": 900, "height": 640, "min_width": 400, "min_height": 300,
                "resizable": True, "always_on_top": False, "frameless": False,
                "center": True, "mode": "normal", "title": APP_TITLE,
            },
            "appearance": {"theme": "dark", "font_family": "Arial",
                           "font_size": 13, "zoom": 1.0},
            "features": {"gpu_acceleration": True, "devtools": True,
                         "cache": True, "sandbox": False, "hot_reload": True,
                         "notifications": True},
            "network": {"user_agent": "ViElectron/%s" % VERSION,
                        "proxy": "", "timeout": 20},
        }

    # ------------------------------------------------------------------- ui
    def _build_ui(self):
        w = self.config["window"]
        geo = "%dx%d" % (w["width"], w["height"])
        if w.get("center"):
            self.root.geometry(geo)
            self.root.update_idletasks()
            x = (self.root.winfo_screenwidth() - w["width"]) // 2
            y = (self.root.winfo_screenheight() - w["height"]) // 2
            self.root.geometry("%s+%d+%d" % (geo, max(x, 0), max(y, 0)))
        else:
            self.root.geometry(geo)
        self.root.minsize(w["min_width"], w["min_height"])
        self.root.resizable(w["resizable"], w["resizable"])
        if w["always_on_top"]:
            self.root.attributes("-topmost", True)
        if w["frameless"]:
            try:
                self.root.overrideredirect(True)
            except tk.TclError:
                pass
        if w["mode"] == "fullscreen":
            try:
                self.root.attributes("-fullscreen", True)
            except tk.TclError:
                pass
        elif w["mode"] == "maximized":
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass

        self.apply_theme(self.config["appearance"]["theme"])

        # Верхняя панель: адресная строка + кнопки (в продакшене скрыта)
        self.toolbar = tk.Frame(self.root, bg=self.theme["panel"], padx=6, pady=4)
        if not self.production:
            self.toolbar.pack(fill="x")
        self.url_entry = tk.Entry(self.toolbar, font=(self.config["appearance"]["font_family"], 11),
                                  relief=tk.FLAT, bg=self.theme["content_bg"],
                                  fg=self.theme["fg"], insertbackground=self.theme["fg"])
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.url_entry.bind("<Return>", lambda e: self.load_url(self.url_entry.get()))
        for text, cmd in (("⟳ Reload", self.reload),
                          ("🏠 Home", lambda: self.render_html(self.start_html)),
                          ("⚙ Настройки", lambda: ConfigWizard(self.root, self.config, self.on_config_applied))):
            tk.Button(self.toolbar, text=text, command=cmd, relief=tk.FLAT,
                      bg=self.theme["accent"], fg=self.theme["content_bg"]).pack(side="right", padx=2)

        # Статус-бар ОС / WM — «как в Electron» показываем цель сборки
        info = "target: %s | WM: %s | host: %s (%s) | python %s" % (
            self.config["os_target"], self.config["window_manager"],
            platform.system(), detect_platform(), platform.python_version())
        self.status = tk.Label(self.root, text=info, anchor="w",
                               bg=self.theme["panel"], fg=self.theme["fg"],
                               font=("Consolas", 9), padx=8)
        self.status.pack(fill="x", side="bottom")

        # DevTools-консоль снизу
        self.console_frame = tk.Frame(self.root, bg=self.theme["panel"])
        if self.config["features"]["devtools"] and not self.production:
            self.console_frame.pack(fill="y", side="bottom")
            self.console = tk.Text(self.console_frame, height=8, bg=self.theme["content_bg"],
                                   fg="#9ece6a", insertbackground=self.theme["fg"],
                                   relief=tk.FLAT, font=("Consolas", 10), state="disabled")
            self.console.pack(fill="both", expand=True, padx=4, pady=4)
            self.err_count = tk.Label(self.console_frame, text="", bg=self.theme["panel"],
                                      fg=self.theme["fg"], font=("Consolas", 9))
            self.err_count.pack(anchor="e", padx=8)
        else:
            self.console = None
        self.errors = 0

        # Область контента (<webview>)
        self.content = ContentFrame(self.root, self)
        self.content.pack(fill="both", expand=True)

        # Toast-уведомления (аналог Notification API)
        self._toast_widget = None

    def apply_theme(self, theme_name):
        self.theme = THEMES.get(theme_name, THEMES["dark"])
        self.root.configure(bg=self.theme["bg"])
        if hasattr(self, "content"):
            self.content.apply_theme()

    def on_config_applied(self, new_config):
        self.config = new_config
        w = new_config["window"]
        self.root.title(w["title"])
        self.apply_theme(new_config["appearance"]["theme"])
        self.log("engine", "Конфигурация применена: %s / %s" %
                 (w["width"], w["height"]))

    # ---------------------------------------------------------------- keys
    def _bind_keys(self):
        self.root.bind("<Control-r>", lambda e: self.reload())
        self.root.bind("<Control-l>", lambda e: (self.url_entry.focus_set(),
                                                 self.url_entry.select_range(0, tk.END)))
        self.root.bind("<Control-Shift-j>", lambda e: self.toggle_console())
        self.root.bind("<Escape>", lambda e: self._close_fullscreen())

    def toggle_console(self):
        if self.console is None:
            return
        if self.console_frame.winfo_ismapped():
            self.console_frame.pack_forget()
        else:
            self.console_frame.pack(fill="y", side="bottom", before=self.status)

    def _close_fullscreen(self):
        try:
            self.root.attributes("-fullscreen", False)
        except tk.TclError:
            pass

    # -------------------------------------------------------------- loading
    def reload(self):
        if self.start_url:
            self.load_url(self.start_url, force=True)
        else:
            self.render_html(self.start_html)
            self.log("engine", "Hot reload выполнен")

    def load_url(self, raw, force=False):
        raw = raw.strip()
        if not raw:
            return
        if not re.match(r"^https?://", raw):
            raw = "https://" + raw
        self.start_url = raw
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, raw)
        self.log("engine", "Загрузка: " + raw)
        if not HAVE_REQUESTS:
            self.show_error("Модуль requests недоступен — показываю локальную страницу.")
            return

        def worker():
            try:
                proxies = {}
                px = self.config["network"].get("proxy")
                if px:
                    proxies = {"http": px, "https": px}
                resp = requests.get(raw, timeout=self.config["network"]["timeout"],
                                    headers={"User-Agent": self.config["network"]["user_agent"]},
                                    proxies=proxies or None)
                resp.encoding = resp.encoding or "utf-8"
                self.msg_queue.put(("page", resp.text))
            except Exception as e:
                self.msg_queue.put(("error", str(e)))
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(80, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "page":
                    self.render_html(payload)
                    self.log("engine", "Страница загружена (%d байт)" % len(payload))
                elif kind == "error":
                    self.show_error("Не удалось загрузить страницу:\n" + payload)
        except queue.Empty:
            pass
        if self.msg_queue.empty() is False or True:
            self.root.after(80, self._poll_queue)

    def show_error(self, message):
        self.log("engine", "ERROR: " + message.replace("\n", " "))
        box = tk.Frame(self.content.inner, bg=self.theme["content_bg"], pady=40)
        box.pack(expand=True)
        tk.Label(box, text="⚠", font=("Arial", 48), bg=self.theme["content_bg"],
                 fg="#f7768e").pack()
        tk.Label(box, text=message, font=("Arial", 12), wraplength=520, justify="center",
                 bg=self.theme["content_bg"], fg=self.theme["fg"]).pack(pady=10)

    # ------------------------------------------------------------- renderer
    def render_html(self, html):
        """Рендерим страницу через viengine_dom (или мини-парсер) + исполняем JS."""
        self.content.clear()
        self.content.apply_theme()
        self.start_html = html
        style_text = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
        self.style_map = self._parse_css(style_text)
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
        body_html = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", html)
        body_html = re.sub(r"(?s)<!DOCTYPE.*?>", "", body_html)

        self.page_document = None
        if HAVE_VIENGINE:
            try:
                doc = parse_html(body_html)
                self.page_document = doc
                root_node = getattr(doc, "body", None) or doc.documentElement or doc
                self._render_node(root_node)
            except Exception as e:
                self.log("engine", "viengine_dom не справился (%s), мини-рендер" % e)
                self._render_mini(body_html)
        else:
            self._render_mini(body_html)

        self._run_scripts(scripts)
        try:
            self.root.update_idletasks()
        except AttributeError:
            pass

    def _parse_css(self, css):
        rules = {}
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            props = {}
            for decl in body.split(";"):
                if ":" in decl:
                    k, v = decl.split(":", 1)
                    props[k.strip().lower()] = v.strip()
            for s in sel.split(","):
                s = s.strip()
                if s:
                    rules.setdefault(s, {}).update(props)
        return rules

    def _style_for(self, node):
        out = {}
        tag = getattr(node, "localName", None) or getattr(node, "tag", "") or ""
        attrs = getattr(node, "attributes", None)
        if attrs is None:
            attrs = getattr(node, "attrs", {}) or {}
        cls = attrs.get("class", "")
        nid = attrs.get("id", "")
        for sel, props in self.style_map.items():
            sel = sel.strip()
            ok = False
            if sel == tag:
                ok = True
            elif sel.startswith(".") and sel[1:] in cls.split():
                ok = True
            elif sel.startswith("#") and sel[1:] == nid:
                ok = True
            if ok:
                out.update(props)
        inline = attrs.get("style", "")
        for decl in inline.split(";"):
            if ":" in decl:
                k, v = decl.split(":", 1)
                out[k.strip().lower()] = v.strip()
        return out

    CSS_COLORS = {
        "white": "#ffffff", "black": "#000000", "red": "#e5484d", "green": "#46a758",
        "blue": "#4f7cff", "yellow": "#f8d849", "gray": "#8a8f98", "grey": "#8a8f98",
        "orange": "#f0883e", "purple": "#a855f7", "pink": "#ec4899",
        "transparent": None, "inherit": None,
    }

    def _color(self, value, default):
        if not value:
            return default
        v = value.strip().lower()
        if v in self.CSS_COLORS:
            c = self.CSS_COLORS[v]
            return c if c else default
        if re.match(r"^#[0-9a-fA-F]{3,8}$", v):
            return v[:7] if len(v) > 7 else v
        if v.startswith("rgb"):
            nums = re.findall(r"\d+", v)[:3]
            if len(nums) == 3:
                return "#%02x%02x%02x" % tuple(int(n) % 256 for n in nums)
        return default

    def _node_attrs(self, node):
        attrs = getattr(node, "attributes", None)
        if isinstance(attrs, dict):
            return attrs
        return getattr(node, "attrs", {}) or {}

    def _render_node(self, node):
        """Рекурсивный рендер DOM-узла viengine в виджеты Tkinter."""
        if node is None:
            return
        # Текстовые узлы viengine_dom: nodeType == Node.TEXT_NODE (3)
        if getattr(node, "nodeType", None) == 3:
            txt = getattr(node, "data", "") or getattr(node, "textContent", "")
            if txt and txt.strip():
                self._make_label(" ".join(txt.split()), {})
            return
        if getattr(node, "nodeType", None) in (8, 9, 11):
            for child in list(getattr(node, "childNodes", []) or []):
                self._render_node(child)
            return
        tag = (getattr(node, "localName", None) or getattr(node, "tag", "") or "").lower()
        if not tag:
            txt = _text_of(node)
            if txt:
                self._make_label(txt, {})
            return
        attrs = self._node_attrs(node)
        children = list(getattr(node, "children", []) or [])
        if tag in ("head", "title", "meta", "link", "script", "style"):
            return
        if tag == "br":
            tk.Frame(self.content.inner, height=6, bg=self.theme["content_bg"]).pack()
            return
        if tag in ("html", "body", "div", "section", "article", "main", "header",
                   "footer", "nav", "ul", "ol", "li", "form", "fieldset", "p",
                   "span", "label", "tr", "td", "table", "blockquote", "figure"):
            style = self._style_for(node)
            frame = tk.Frame(self.content.inner,
                             bg=self._color(style.get("background-color") or style.get("background"),
                                            self.theme["content_bg"]))
            pad = _px(style.get("padding"))
            frame.pack(fill="x", padx=_px(style.get("margin")),
                       pady=(pad, pad) if pad else (0, 2))
            old_inner = self.content.inner
            self.content.inner = frame
            for child in children:
                self._render_node(child)
            self.content.inner = old_inner
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            sizes = {"h1": 26, "h2": 22, "h3": 18, "h4": 16, "h5": 14, "h6": 13}
            style = self._style_for(node)
            text = _text_of(node)
            if text:
                lbl = tk.Label(self.content.inner, text=text, anchor="w",
                               justify="left", wraplength=680,
                               font=(self.config["appearance"]["font_family"],
                                     sizes[tag], "bold"),
                               bg=self._color(style.get("background-color") or style.get("background"),
                                              self.theme["content_bg"]),
                               fg=self._color(style.get("color"), self.theme["content_fg"]))
                lbl.pack(fill="x", pady=4)
            return
        if tag == "a":
            href = attrs.get("href", "#")
            text = _text_of(node) or href
            style = self._style_for(node)
            lbl = tk.Label(self.content.inner, text=text, anchor="w",
                           font=(self.config["appearance"]["font_family"],
                                 self.config["appearance"]["font_size"], "underline"),
                           bg=self.theme["content_bg"],
                           fg=self._color(style.get("color"), self.theme["accent"]))
            lbl.pack(anchor="w", pady=2)
            lbl.bind("<Button-1>", lambda e, h=href: self._follow_link(h))
            return
        if tag == "img":
            src = attrs.get("src", "")
            tk.Label(self.content.inner, text="[IMG %s]" % src[:60],
                     bg=self.theme["content_bg"], fg=self.theme["fg"],
                     font=("Consolas", 9)).pack(anchor="w", pady=2)
            return
        if tag == "input":
            itype = attrs.get("type", "text")
            if itype in ("submit", "button"):
                self._make_button(attrs.get("value", "Button"), attrs)
            else:
                ent = tk.Entry(self.content.inner, relief=tk.FLAT,
                               bg=self.theme["panel"], fg=self.theme["fg"],
                               insertbackground=self.theme["fg"])
                ent.pack(anchor="w", fill="x", pady=2)
                attrs["_widget"] = ent
            return
        if tag == "button":
            self._make_button(_text_of(node) or "Button", attrs)
            return
        text = _text_of(node)
        if text:
            self._make_label(text, self._style_for(node))
        else:
            for child in children:
                self._render_node(child)

    def _make_label(self, text, style):
        fam = self.config["appearance"]["font_family"]
        size = self.config["appearance"]["font_size"]
        weight = "bold" if style.get("font-weight") in ("bold", "600", "700", "800", "900") else "normal"
        align = {"center": "center", "right": "e"}.get(style.get("text-align"), "w")
        lbl = tk.Label(self.content.inner, text=text, wraplength=680, justify="left",
                       anchor=align, font=(fam, size, weight),
                       bg=self._color(style.get("background-color") or style.get("background"),
                                      self.theme["content_bg"]),
                       fg=self._color(style.get("color"), self.theme["content_fg"]))
        lbl.pack(fill="x", pady=1)

    def _make_button(self, text, attrs):
        onclick = attrs.get("onclick", "")
        btn = tk.Button(self.content.inner, text=text, relief=tk.FLAT,
                        bg=self.theme["accent"], fg=self.theme["content_bg"],
                        font=(self.config["appearance"]["font_family"],
                              self.config["appearance"]["font_size"]),
                        command=lambda: self._fire_inline(onclick, text))
        btn.pack(anchor="center", pady=8)

    def _follow_link(self, href):
        if href.startswith("http"):
            self.load_url(href)
        else:
            self.log("engine", "Якорь/локальная ссылка: %s" % href)

    # ------------------------------------------------------------ rendering
    # без viengine_dom: очень простой линейный рендер
    def _render_mini(self, body_html):
        fam = self.config["appearance"]["font_family"]
        size = self.config["appearance"]["font_size"]
        for m in re.finditer(
                r"<(?P<tag>h[1-6]|p|button|a|input|textarea|div|span|li)([^>]*)>(?P<text>[^<]*)",
                body_html):
            tag = m.group("tag")
            attrs_raw = m.group(2)
            text = m.group(3).strip()
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_raw))
            if not text and tag not in ("button", "input"):
                continue
            if tag in ("button",) or (tag == "input" and attrs.get("type") in ("submit", "button")):
                self._make_button(text or attrs.get("value", "Button"), attrs)
            elif tag == "a":
                self._follow_label(text, attrs.get("href", "#"))
            elif tag.startswith("h"):
                lbl = tk.Label(self.content.inner, text=text, font=(fam, size + 8 - int(tag[1]) * 0, "bold"),
                               bg=self.theme["content_bg"], fg=self.theme["content_fg"], anchor="w")
                lbl.pack(fill="x", pady=4)
            else:
                tk.Label(self.content.inner, text=text, font=(fam, size),
                         bg=self.theme["content_bg"], fg=self.theme["content_fg"],
                         anchor="w", wraplength=680, justify="left").pack(fill="x", pady=1)

    def _follow_label(self, text, href):
        lbl = tk.Label(self.content.inner, text=text, font=("Arial", 12, "underline"),
                       bg=self.theme["content_bg"], fg=self.theme["accent"], anchor="w")
        lbl.pack(anchor="w")
        lbl.bind("<Button-1>", lambda e: self._follow_link(href))

    # ------------------------------------------------------------------- JS
    def _make_js_globals(self):
        """Готовит окружение для viengine_js: console, window.viElectron, document."""
        app = self

        class Bridge:
            def toast(self, msg):
                app.toast(str(msg))

            def setTitle(self, title):
                app._set_title(str(title))

            def close(self):
                app._close_window()

            def log(self, msg):
                app.log("js", str(msg))

            def getPlatform(self):
                return detect_platform()

            def getWindowConfig(self):
                return json.loads(json.dumps(app.config["window"]))

            def getOsTarget(self):
                return app.config["os_target"]

            def getWindowManager(self):
                return app.config["window_manager"]

        console_obj = {
            "log": lambda *args: app.log("js", " ".join(str(a) for a in args)),
            "warn": lambda *args: app.log("js", "WARN: " + " ".join(str(a) for a in args)),
            "error": lambda *args: self._console_error(" ".join(str(a) for a in args)),
        }
        window_obj = {
            "viElectron": Bridge(),
            "alert": lambda msg: app.toast(str(msg)),
            "innerWidth": 900,
            "innerHeight": 640,
            "platform": detect_platform(),
        }
        doc_obj = {}
        if getattr(self, "page_document", None) is not None:
            doc_obj = {
                "getElementById": self.page_document.getElementById,
                "querySelector": self.page_document.querySelector,
                "querySelectorAll": self.page_document.querySelectorAll,
            }
        return {"console": console_obj, "window": window_obj, "document": doc_obj}

    def _console_error(self, message):
        self.errors += 1
        self.log("js", "ERROR: " + message)

    def _run_scripts(self, scripts):
        if not scripts:
            return
        if HAVE_VIENGINE:
            try:
                eng = JavaScriptEngine()
                js_globals = self._make_js_globals()
                first = True
                for code in scripts:
                    if not code.strip():
                        continue
                    try:
                        eng.execute(code, globals=dict(js_globals) if first else None)
                        first = False
                    except Exception as e:
                        self.log("js", "Ошибка выполнения: %s" % e)
                try:
                    eng.run_timers(limit=200)
                except Exception:
                    pass
                self.js_engine = ("viengine", eng)
                self.log("js", "Выполнено скриптов: %d (viengine_js)" % len(scripts))
                return
            except Exception as e:
                self.log("js", "viengine_js недоступен полностью: %s" % e)
        mini = MiniJS(self)
        for code in scripts:
            mini.run_script(code)
        self.js_engine = ("mini", mini)

    def _fire_inline(self, onclick, label):
        if not onclick:
            self.log("js", "Кнопка «%s» без обработчика" % label)
            return
        kind, engine = (self.js_engine or ("none", None))
        if kind == "viengine":
            try:
                engine.execute(onclick)
                engine.run_timers(limit=50)
                return
            except Exception as e:
                self.log("js", "inline onclick error: %s" % e)
        elif kind == "mini":
            try:
                engine.eval_expr(onclick.rstrip(";"))
            except Exception as e:
                self.log("js", "mini onclick error: %s" % e)

    # ------------------------------------------------------------ JS APIs
    class DomApi:
        def __init__(self, app):
            self.app = app

        def getElementById(self, el_id):
            app = self.app

            class El:
                def __init__(self, eid):
                    self.id = eid
                    self._text = ""

                @property
                def textContent(self):
                    return self._text

                @textContent.setter
                def textContent(self, v):
                    self._text = str(v)
                    app.log("dom", "#%s.textContent = %r" % (eid, v))

                @property
                def innerHTML(self):
                    return self._text

                @innerHTML.setter
                def innerHTML(self, v):
                    self.textContent = v

            return El(el_id)

        def querySelector(self, sel):
            return self.getElementById(sel)

        def createElement(self, tag):
            return self.DomElement(tag)

    class DomElement:
        def __init__(self, tag):
            self.tag = tag

    class ConsoleApi:
        def __init__(self, app):
            self.app = app

        def log(self, *args):
            self.app.log("js", " ".join(str(a) for a in args))

        def error(self, *args):
            self.app.errors += 1
            self.app.log("js", "ERROR: " + " ".join(str(a) for a in args))
            if self.app.err_count:
                self.app.err_count.configure(text="errors: %d" % self.app.errors)

        warn = error

    class WindowApi:
        def __init__(self, app):
            self.app = app

        def alert(self, msg):
            self.app.toast(str(msg))

    # -------------------------------------------------------------- bridge
    @property
    def dom_api(self):
        if not hasattr(self, "_dom_api"):
            self._dom_api = ViElectronApp.DomApi(self)
        return self._dom_api

    @property
    def console_api(self):
        if not hasattr(self, "_console_api"):
            self._console_api = ViElectronApp.ConsoleApi(self)
        return self._console_api

    @property
    def window_api(self):
        if not hasattr(self, "_window_api"):
            self._window_api = ViElectronApp.WindowApi(self)
        return self._window_api

    # ------------------------------------------------------------- helpers
    def log(self, channel, message):
        stamp = "%s [%s] %s" % (_now(), channel.upper(), message)
        if self.console:
            self.console.configure(state="normal")
            self.console.insert(tk.END, stamp + "\n")
            tags = ()
            if "ERROR" in message:
                tags = ("err",)
            self.console.see(tk.END)
            self.console.configure(state="disabled")
        else:
            print(stamp)

    def toast(self, message):
        if not self.config["features"]["notifications"]:
            return
        if self._toast_widget:
            try:
                self._toast_widget.destroy()
            except tk.TclError:
                pass
        t = tk.Label(self.root, text=str(message), bg="#9ece6a", fg="#14151a",
                     font=("Arial", 11, "bold"), padx=14, pady=8)
        t.place(relx=0.5, rely=0.06, anchor="n")
        self._toast_widget = t
        self.root.after(2600, lambda: t.winfo_exists() and t.destroy())

    def _set_title(self, title):
        self.root.title(title)
        self.config["window"]["title"] = title

    def _close_window(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def _px(value):
    if not value:
        return 0
    m = re.match(r"(\d+)", str(value))
    return int(m.group(1)) if m else 0


def _text_of(node):
    parts = []
    if isinstance(getattr(node, "text", None), str):
        parts.append(node.text)
    for child in getattr(node, "children", []):
        t = _text_of(child)
        if t:
            parts.append(t)
    return " ".join(" ".join(parts).split())


def _first(args):
    try:
        return args[0]
    except Exception:
        return args


def _now():
    import datetime
    return datetime.datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Мастер настройки: ОС, WM, размеры, темы и «дохуя всего»
# ---------------------------------------------------------------------------

class ConfigWizard(tk.Toplevel):
    STEPS = ("ОС", "Оконный менеджер", "Окно", "Внешний вид", "Функции", "Сеть", "Итог")

    def __init__(self, master, config, on_apply):
        super().__init__(master)
        self.title("ViElectron — мастер конфигурации")
        self.geometry("640x520")
        self.resizable(False, False)
        self.config_data = json.loads(json.dumps(config))  # deep copy
        self.on_apply = on_apply
        self.step = 0
        self.vars = {}

        self.header = tk.Label(self, text="", font=("Arial", 15, "bold"), pady=10)
        self.header.pack()
        self.body = tk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=18)
        nav = tk.Frame(self, pady=10)
        nav.pack(fill="x", padx=18)
        self.btn_back = tk.Button(nav, text="← Назад", command=self.back)
        self.btn_next = tk.Button(nav, text="Далее →", command=self.next, bg="#7aa2f7")
        self.btn_finish = tk.Button(nav, text="✔ Применить", command=self.apply, bg="#9ece6a")
        self.btn_back.pack(side="left")
        self.btn_finish.pack(side="right")
        self.btn_next.pack(side="right", padx=6)
        self.progress = tk.Label(nav, text="", font=("Arial", 9))
        self.progress.pack(side="left")
        self.show_step()

    # ----------------------------------------------------------- navigation
    def show_step(self):
        for w in self.body.winfo_children():
            w.destroy()
        name = self.STEPS[self.step]
        self.header.configure(text="Шаг %d/%d — %s" % (self.step + 1, len(self.STEPS), name))
        self.progress.configure(text=" → ".join(self.STEPS))
        self.btn_back.configure(state="normal" if self.step else "disabled")
        self.btn_next.pack_forget()
        self.btn_finish.pack_forget()
        if self.step < len(self.STEPS) - 1:
            self.btn_next.pack(side="right", padx=6)
        else:
            self.btn_finish.pack(side="right")
        getattr(self, "step_" + str(self.step))()

    def back(self):
        self.step = max(0, self.step - 1)
        self.show_step()

    def next(self):
        self.step = min(len(self.STEPS) - 1, self.step + 1)
        self.show_step()

    def apply(self):
        self.on_apply(self.config_data)
        self.destroy()

    # ------------------------------------------------------------- widgets
    def _radio_list(self, key, options, current, row=0):
        var = tk.StringVar(value=current)
        self.vars[key] = var
        for i, opt in enumerate(options):
            rb = tk.Radiobutton(self.body, text=opt, variable=var, value=opt,
                                font=("Arial", 11), anchor="w", justify="left")
            rb.grid(row=row + i, column=0, sticky="w", pady=2)
        return var

    # ---------------------------------------------------------- step 0: OS
    def step_0(self):
        tk.Label(self.body, text="Целевая операционная система приложения:",
                 font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        cur = self.config_data["os_target"]
        var = self._radio_list("os_target", list(OS_TARGETS), cur, row=1)
        tk.Label(self.body, text="Текущая ОС хоста: %s (%s)" %
                 (platform.system(), platform.release()),
                 font=("Arial", 9), fg="gray").grid(row=1 + len(OS_TARGETS), column=0, sticky="w", pady=8)
        self.os_var = var

    # -------------------------------------------------------- step 1: WM
    def step_1(self):
        os_key = self.vars["os_target"].get()
        plat = OS_TARGETS.get(os_key, {}).get("platform", "any")
        wms = WINDOW_MANAGERS.get(plat, WINDOW_MANAGERS["any"])
        tk.Label(self.body, text="Оконный менеджер для %s:" % os_key,
                 font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        cur = self.config_data["window_manager"]
        if cur not in wms:
            cur = OS_TARGETS.get(os_key, {}).get("default_wm", wms[0])
            if cur not in wms:
                cur = wms[-1]
        self._radio_list("window_manager", wms, cur, row=1)
        tk.Label(self.body, text="Реально запущенный WM: " + detect_window_manager(),
                 font=("Arial", 9), fg="gray").grid(row=1 + len(wms), column=0, sticky="w", pady=8)

    # -------------------------------------------------------- step 2: window
    def step_2(self):
        w = self.config_data["window"]
        rows = [("title", "Заголовок окна"), ("width", "Ширина"), ("height", "Высота"),
                ("min_width", "Min ширина"), ("min_height", "Min высота")]
        for i, (key, label) in enumerate(rows):
            tk.Label(self.body, text=label + ":", font=("Arial", 10)).grid(row=i, column=0, sticky="w")
            var = tk.StringVar(value=str(w[key]))
            self.vars["w_" + key] = var
            tk.Entry(self.body, textvariable=var, width=28).grid(row=i, column=1, sticky="w", pady=2)
        checks = [("resizable", "Можно изменять размер"), ("always_on_top", "Поверх всех окон"),
                  ("frameless", "Без рамки (frameless)"), ("center", "Центрировать при старте")]
        base = len(rows)
        for i, (key, label) in enumerate(checks):
            var = tk.BooleanVar(value=bool(w[key]))
            self.vars["w_" + key] = var
            tk.Checkbutton(self.body, text=label, variable=var).grid(row=base + i, column=0, sticky="w")
        tk.Label(self.body, text="Режим окна:").grid(row=base + len(checks), column=0, sticky="w")
        mode_var = tk.StringVar(value=w["mode"])
        self.vars["w_mode"] = mode_var
        ttk.Combobox(self.body, textvariable=mode_var, width=16, state="readonly",
                     values=["normal", "maximized", "fullscreen", "minimized"]).grid(
            row=base + len(checks), column=1, sticky="w")

    # ------------------------------------------------------ step 3: look
    def step_3(self):
        ap = self.config_data["appearance"]
        tk.Label(self.body, text="Тема оформления:", font=("Arial", 10)).grid(row=0, column=0, sticky="w")
        theme_var = tk.StringVar(value=ap["theme"])
        self.vars["theme"] = theme_var
        box = tk.Frame(self.body)
        box.grid(row=1, column=0, columnspan=2, sticky="w")
        for i, name in enumerate(THEMES):
            th = THEMES[name]
            b = tk.Radiobutton(box, text=name, variable=theme_var, value=name,
                               bg=th["bg"], fg=th["fg"], selectcolor=th["panel"],
                               activebackground=th["bg"], activeforeground=th["fg"],
                               font=("Arial", 10))
            b.grid(row=i // 3, column=i % 3, padx=6, pady=4)
        tk.Label(self.body, text="Шрифт:").grid(row=4, column=0, sticky="w", pady=(10, 0))
        fam_var = tk.StringVar(value=ap["font_family"])
        self.vars["font_family"] = fam_var
        ttk.Combobox(self.body, textvariable=fam_var, values=FONT_FAMILIES, width=22).grid(row=5, column=0, sticky="w")
        tk.Label(self.body, text="Размер шрифта:").grid(row=6, column=0, sticky="w", pady=(8, 0))
        size_var = tk.IntVar(value=ap["font_size"])
        self.vars["font_size"] = size_var
        tk.Scale(self.body, from_=9, to=22, orient="horizontal", variable=size_var).grid(row=7, column=0, sticky="w")
        tk.Label(self.body, text="Масштаб (zoom):").grid(row=6, column=1, sticky="w", pady=(8, 0))
        zoom_var = tk.DoubleVar(value=ap["zoom"])
        self.vars["zoom"] = zoom_var
        tk.Scale(self.body, from_=0.6, to=2.0, resolution=0.1, orient="horizontal",
                 variable=zoom_var).grid(row=7, column=1, sticky="w")

    # ---------------------------------------------------- step 4: features
    def step_4(self):
        f = self.config_data["features"]
        labels = {
            "gpu_acceleration": "Аппаратное ускорение отрисовки",
            "devtools": "DevTools-консоль (Ctrl+Shift+J)",
            "cache": "Локальный кэш (local_cache)",
            "sandbox": "Песочница для JS (изоляция)",
            "hot_reload": "Hot Reload (Ctrl+R)",
            "notifications": "Toast-уведомления (Notification API)",
        }
        for i, (key, label) in enumerate(labels.items()):
            var = tk.BooleanVar(value=bool(f[key]))
            self.vars["f_" + key] = var
            tk.Checkbutton(self.body, text=label, variable=var,
                           font=("Arial", 11)).grid(row=i, column=0, sticky="w", pady=3)
        tk.Label(self.body, text="\nДвижок viengine обнаружен: " +
                 ("ДА ✔" if HAVE_VIENGINE else "НЕТ (используется мини-рендер)"),
                 font=("Arial", 10, "bold")).grid(row=len(labels) + 1, column=0, sticky="w")

    # ------------------------------------------------------- step 5: network
    def step_5(self):
        n = self.config_data["network"]
        for i, (key, label) in enumerate([("user_agent", "User-Agent"),
                                          ("proxy", "Прокси (http://host:port)"),
                                          ("timeout", "Таймаут запроса, сек")]):
            tk.Label(self.body, text=label + ":", font=("Arial", 10)).grid(row=i, column=0, sticky="w")
            var = tk.StringVar(value=str(n[key]))
            self.vars["n_" + key] = var
            tk.Entry(self.body, textvariable=var, width=44).grid(row=i, column=1, sticky="w", pady=3)

    # --------------------------------------------------------- step 6: summary
    def step_6(self):
        self._collect()
        text = json.dumps(self.config_data, indent=2, ensure_ascii=False)
        tk.Label(self.body, text="Итоговая конфигурация (package.json):",
                 font=("Arial", 11, "bold")).pack(anchor="w")
        box = tk.Text(self.body, height=20, font=("Consolas", 10), bg="#14151a", fg="#9ece6a")
        box.pack(fill="both", expand=True, pady=6)
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _collect(self):
        c = self.config_data
        c["os_target"] = self.vars["os_target"].get()
        c["window_manager"] = self.vars["window_manager"].get()
        w = c["window"]
        for key in ("title", "mode"):
            w[key] = self.vars["w_" + key].get()
        for key in ("width", "height", "min_width", "min_height"):
            try:
                w[key] = int(self.vars["w_" + key].get())
            except ValueError:
                pass
        for key in ("resizable", "always_on_top", "frameless", "center"):
            w[key] = bool(self.vars["w_" + key].get())
        ap = c["appearance"]
        ap["theme"] = self.vars["theme"].get()
        ap["font_family"] = self.vars["font_family"].get()
        ap["font_size"] = int(self.vars["font_size"].get())
        ap["zoom"] = float(self.vars["zoom"].get())
        for key in ("gpu_acceleration", "devtools", "cache", "sandbox", "hot_reload", "notifications"):
            c["features"][key] = bool(self.vars["f_" + key].get())
        n = c["network"]
        n["user_agent"] = self.vars["n_user_agent"].get()
        n["proxy"] = self.vars["n_proxy"].get()
        try:
            n["timeout"] = int(float(self.vars["n_timeout"].get()))
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Редактор кода с подсветкой, нумерацией строк и поиском
# ---------------------------------------------------------------------------

class CodeEditor(tk.Frame):
    LANGS = ("html", "css", "javascript", "python")

    def __init__(self, master, on_run=None, language="html"):
        super().__init__(master, bg="#1e1f22")
        self.on_run = on_run
        self.language = tk.StringVar(value=language)
        self.search_dir = 1

        top = tk.Frame(self, bg="#26272b")
        top.pack(fill="x")
        ttk.Label(top, text="Файл/язык:", background="#26272b", foreground="#e6e6e6").pack(side="left", padx=(6, 2))
        ttk.Combobox(top, textvariable=self.language, values=self.LANGS, width=12,
                     state="readonly").pack(side="left")
        self.language.trace_add("write", lambda *a: self.rehighlight())
        for text, cmd in (("▶ Запустить", self._run), ("💾 Сохранить", self.save_file),
                          ("📂 Открыть", self.open_file), ("🔍 Найти все", self.find_dialog)):
            tk.Button(top, text=text, command=cmd, relief="flat", bg="#7aa2f7",
                      fg="#14151a").pack(side="right", padx=2, pady=3)

        wrap = tk.Frame(self, bg="#14151a")
        wrap.pack(fill="both", expand=True)
        self.linenums = tk.Canvas(wrap, width=44, bg="#1a1b1e", highlightthickness=0)
        self.linenums.pack(side="left", fill="y")
        self.text = tk.Text(wrap, bg="#14151a", fg="#dcdcdc", insertbackground="#dcdcdc",
                            font=("Consolas", 12), undo=True, wrap="none", relief="flat",
                            padx=6, pady=6)
        self.text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, command=self.text.yview)
        sb.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=self._on_scroll)
        self.linenums.bind("<Button-1>", lambda e: self.text.focus_set())

        for lang in self.LANGS:
            for _, color in SYNTAX_STYLES[lang]:
                self.text.tag_configure(color, foreground=color)
        self.text.tag_configure("searchhl", background="#e0af68", foreground="#14151a")
        self.text.bind("<KeyRelease>", lambda e: self.schedule_highlight())
        self._hl_job = None
        self.set_text(DEFAULT_MAIN_HTML)

    def _on_scroll(self, first, last):
        self.linenums.yview_moveto(first)
        self.redraw_line_numbers()

    def hide(self):
        self.pack_forget()

    def set_text(self, content):
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        self.rehighlight()

    def get_text(self):
        return self.text.get("1.0", tk.END)

    def schedule_highlight(self):
        if self._hl_job:
            self.text.after_cancel(self._hl_job)
        self._hl_job = self.text.after(220, self.rehighlight)

    def rehighlight(self):
        if self._hl_job:
            self.text.after_cancel(self._hl_job)
            self._hl_job = None
        content = self.get_text()
        for _, color in SYNTAX_STYLES.get(self.language.get(), []):
            self.text.tag_remove(color, "1.0", tk.END)
        for pattern, color in SYNTAX_STYLES.get(self.language.get(), []):
            for m in re.finditer(pattern, content):
                start = "1.%d" % (m.start() + 1)
                end = "1.%d" % (m.end() + 1)
                idx_start = self.text.index(start)
                idx_end = self.text.index(end)
                try:
                    self.text.tag_add(color, idx_start, idx_end)
                except tk.TclError:
                    pass
        self.redraw_line_numbers()

    def redraw_line_numbers(self):
        self.linenums.delete("all")
        total = int(self.text.index("end-1c").split(".")[0])
        first_line = int(self.text.index("@0,0").split(".")[0])
        last_line = int(self.text.index("@0,%d" % self.text.winfo_height()).split(".")[0])
        y = 6
        for lineno in range(max(1, first_line), min(total, last_line) + 2):
            dline = self.text.dlineinfo(lineno)
            if dline is None:
                continue
            x, y, w, h, _ = dline
            self.linenums.create_text(38, y + h / 2, anchor="e", text=str(lineno),
                                      fill="#5a5e68", font=("Consolas", 11))

    # ------------------------------------------------------------ actions
    def _run(self):
        if self.on_run:
            self.on_run(self.get_text(), self.language.get())

    def find_dialog(self):
        dlg = tk.simple_dialog = tk.Toplevel(self)
        dlg.title("Поиск")
        entry = tk.Entry(dlg, width=30)
        entry.pack(padx=8, pady=8)
        case = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text="Учитывать регистр", variable=case).pack()
        replace_var = tk.StringVar()
        tk.Entry(dlg, textvariable=replace_var, width=30).pack(pady=(0, 4))

        def do_find():
            self.text.tag_remove("searchhl", "1.0", tk.END)
            pat = entry.get()
            if not pat:
                return
            flags = 0 if case.get() else re.I
            for m in re.finditer(re.escape(pat), self.get_text(), flags):
                s = "1.%d" % (m.start() + 1)
                e = "1.%d" % (m.end() + 1)
                self.text.tag_add("searchhl", self.text.index(s), self.text.index(e))
            first = self.text.search(pat, "1.0", tk.END, nocase=not case.get())
            if first:
                self.text.mark_set(tk.INSERT, first)
                self.text.see(first)

        def do_replace():
            content = self.get_text()
            new = re.sub(re.escape(entry.get()), replace_var.get(), content,
                         flags=0 if case.get() else re.I)
            self.set_text(new)

        tk.Button(dlg, text="Найти все", command=do_find).pack(pady=4)
        tk.Button(dlg, text="Заменить всё", command=do_replace).pack(pady=4)
        entry.focus_set()

    def find_next(self):
        self.text.event_generate("<Control-f>")

    def open_file(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[
            ("HTML", "*.html"), ("CSS", "*.css"), ("JavaScript", "*.js"),
            ("Python", "*.py"), ("Все файлы", "*.*")])
        if path:
            self.set_text(Path(path).read_text(encoding="utf-8", errors="replace"))
            ext = Path(path).suffix.lower()
            self.language.set({"html": "html", "css": "css", "js": "javascript",
                               "py": "python"}.get(ext.lstrip("."), "html"))

    def save_file(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".html",
                                            filetypes=[("HTML", "*.html"), ("CSS", "*.css"),
                                                       ("JavaScript", "*.js"), ("Python", "*.py")])
        if path:
            Path(path).write_text(self.get_text(), encoding="utf-8")
            self.blink("Сохранено: " + path)

    def blink(self, message):
        pass


# ---------------------------------------------------------------------------
# Главное IDE-окно (launcher): мастер + редактор + предпросмотр
# ---------------------------------------------------------------------------

class ViElectronStudio:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("%s · Studio v%s" % (APP_TITLE, VERSION))
        self.config = ViElectronApp.default_config()
        self.config["window"]["title"] = "ViElectron App"
        self.preview_win = None
        self._build_ui()

    def _build_ui(self):
        self.root.geometry("1150x760")
        bar = tk.Frame(self.root, bg="#26272b", pady=6, padx=6)
        bar.pack(fill="x")
        for text, cmd, color in (
                ("🧭 Мастер конфигурации", self.open_wizard, "#7aa2f7"),
                ("🖥 Открыть окно приложения", self.launch_app, "#9ece6a"),
                ("📁 Новый проект…", self.new_project, "#bb9af7"),
                ("💾 Сохранить проект", self.save_project, "#e0af68"),
                ("📂 Открыть проект", self.open_project, "#e0af68"),
                ("📦 Собрать (экспорт)", self.export_project, "#f7768e"),
                ("ℹ О системе", self.show_system_info, "#56b6c2"),
        ):
            tk.Button(bar, text=text, command=cmd, relief="flat", bg=color,
                      fg="#14151a", font=("Arial", 10, "bold")).pack(side="left", padx=3)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # вкладка редактора
        editor_tab = tk.Frame(nb, bg="#1e1f22")
        nb.add(editor_tab, text="  Редактор кода  ")
        self.editor = CodeEditor(editor_tab, on_run=self.run_code, language="html")
        self.editor.pack(fill="both", expand=True)

        # вкладка live-предпросмотра
        self.preview_tab_frame = tk.Frame(nb, bg="#14151a")
        nb.add(self.preview_tab_frame, text="  Предпросмотр  ")

        # статус
        self.statusbar = tk.Label(self.root, anchor="w", bg="#26272b", fg="#9aa5ce",
                                  font=("Consolas", 10), padx=8, pady=4)
        self.statusbar.pack(fill="x")
        self.set_status("Готово. viengine: %s | Целевая ОС: %s | WM: %s" % (
            "подключен" if HAVE_VIENGINE else "мини-режим",
            self.config["os_target"], self.config["window_manager"]))

    def set_status(self, text):
        self.statusbar.configure(text=text)

    # ------------------------------------------------------------- actions
    def open_wizard(self):
        ConfigWizard(self.root, self.config, self.on_wizard_apply)

    def on_wizard_apply(self, cfg):
        self.config = cfg
        self.set_status("Конфигурация обновлена: %s / %s / тема %s" %
                        (cfg["os_target"], cfg["window_manager"], cfg["appearance"]["theme"]))
        if self.preview_win:
            try:
                self.preview_win.on_config_applied(cfg)
            except tk.TclError:
                self.preview_win = None

    def launch_app(self):
        """Открывает отдельное окно приложения — как `electron .`."""
        self.launch_app_with_html(self.editor.get_text())
        self.set_status("Окно приложения открыто (target: %s)." % self.config["os_target"])

    def run_code(self, code, language):
        """Запуск кода из редактора: HTML — в предпросмотр, JS/Python — в консоль."""
        if language == "html":
            self.config["window"]["title"] = "ViElectron App"
            if self.preview_win:
                self.preview_win.render_preview(code)
            else:
                self.launch_app_with_html(code)
            self.set_status("HTML запущен в предпросмотре.")
        elif language == "javascript":
            self.exec_js_snippet(code)
        elif language == "python":
            self.exec_python_snippet(code)
        elif language == "css":
            self.set_status("CSS сохранён как стиль предпросмотра.")
            if self.preview_win:
                self.preview_win.inject_css(code)

    def launch_app_with_html(self, html):
        try:
            self.preview_win.win.destroy()
        except Exception:
            pass
        win = tk.Toplevel(self.root)
        holder = ViElectronInWindow(win, json.loads(json.dumps(self.config)), html)
        self.preview_win = holder
        holder.render_preview(html)

    def exec_js_snippet(self, code):
        if HAVE_VIENGINE:
            try:
                eng = JavaScriptEngine()
                logs = []

                def _log(*args):
                    logs.append(" ".join(str(a) for a in args))
                    self.set_status("JS: " + logs[-1][:120])

                eng.execute(code, globals={"console": {"log": _log, "error": _log,
                                                       "warn": _log},
                                           "window": {}})
                try:
                    eng.run_timers(limit=100)
                except Exception:
                    pass
                self.set_status("JS-сниппет выполнен через viengine_js." +
                                (" → " + logs[-1][:80] if logs else ""))
                return
            except Exception as e:
                self.set_status("viengine_js ошибка: %s" % e)
        else:
            self.set_status("viengine_js недоступен — сниппет не выполнен.")

    def exec_python_snippet(self, code):
        import io
        import contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(compile(code, "<editor>", "exec"), {"__name__": "__visnippet__"})
            out = buf.getvalue().strip()
            self.set_status("Python: " + (out[:120] or "выполнено без вывода"))
        except Exception as e:
            self.set_status("Python ошибка: %s" % e)

    # ------------------------------------------------------------ projects
    def new_project(self):
        name = simple_prompt(self.root, "Новый проект", "Имя приложения:")
        if not name:
            return
        folder = filedialog.askdirectory(title="Куда сохранить проект")
        if not folder:
            return
        proj = Path(folder) / re.sub(r"[^\w-]", "_", name)
        proj.mkdir(parents=True, exist_ok=True)
        cfg = json.loads(json.dumps(self.config))
        cfg["name"] = name
        (proj / "package.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
        (proj / "main.html").write_text(DEFAULT_MAIN_HTML, encoding="utf-8")
        (proj / "app.py").write_text(DEFAULT_APP_PY, encoding="utf-8")
        self.editor.set_text(DEFAULT_MAIN_HTML)
        self.set_status("Создан проект: %s (package.json + main.html + app.py)" % proj)

    def save_project(self):
        folder = filedialog.askdirectory(title="Каталог проекта")
        if not folder:
            return
        proj = Path(folder)
        cfg = json.loads(json.dumps(self.config))
        (proj / "package.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        (proj / "main.html").write_text(self.editor.get_text(), encoding="utf-8")
        (proj / "app.py").write_text(DEFAULT_APP_PY, encoding="utf-8")
        self.set_status("Проект сохранён в %s" % proj)

    def open_project(self):
        folder = filedialog.askdirectory(title="Каталог проекта")
        if not folder:
            return
        try:
            cfg, html = load_project(Path(folder))
        except Exception as e:
            messagebox.showerror("ViElectron", "Не удалось открыть проект: %s" % e)
            return
        self.config = cfg
        self.editor.set_text(html)
        self.set_status("Проект загружен: %s" % folder)

    def export_project(self):
        folder = filedialog.askdirectory(title="Куда экспортировать сборку")
        if not folder:
            return
        dest = Path(folder) / self.config["name"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "package.json").write_text(json.dumps(self.config, indent=2, ensure_ascii=False), encoding="utf-8")
        (dest / "main.html").write_text(self.editor.get_text(), encoding="utf-8")
        (dest / "app.py").write_text(DEFAULT_APP_PY, encoding="utf-8")
        # Копируем модули движка, чтобы сборка была автономной
        for mod in ("viengine.py", "viengine_dom.py", "viengine_css.py",
                    "viengine_js.py", "viengine_js_else.py", "vijs_bridge.py",
                    "local_cache.py", "gif_render.py"):
            src = BASE_DIR / mod
            if src.exists():
                (dest / mod).write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        target_os = self.config["os_target"]
        if messagebox.askyesno("ViElectron",
                               "Сборка готова в %s\nЦелевая ОС: %s\nЗапустить собранное приложение сейчас?" % (dest, target_os)):
            subprocess.Popen([sys.executable, str(dest / "app.py")])
        self.set_status("Экспортировано в %s" % dest)

    def show_system_info(self):
        lines = [
            "Хост: %s %s (%s)" % (platform.system(), platform.release(), detect_platform()),
            "Python: %s" % platform.python_version(),
            "WM хоста: %s" % detect_window_manager(),
            "Целевая ОС: %s" % self.config["os_target"],
            "Выбранный WM: %s" % self.config["window_manager"],
            "viengine подключен: %s" % HAVE_VIENGINE,
            "requests доступен: %s" % HAVE_REQUESTS,
            "Тема: %s | Шрифт: %s %s" % (self.config["appearance"]["theme"],
                                         self.config["appearance"]["font_family"],
                                         self.config["appearance"]["font_size"]),
        ]
        messagebox.showinfo("Система", "\n".join(lines))

    def run(self):
        self.root.mainloop()


class ViElectronInWindow:
    """ViElectron-приложение внутри Toplevel (для предпросмотра в Studio)."""

    def __init__(self, win, config, html):
        self.win = win
        self.config = config
        win.title(config["window"]["title"])
        win.geometry("%dx%d" % (config["window"]["width"], config["window"]["height"]))
        self.theme = THEMES.get(config["appearance"]["theme"], THEMES["dark"])
        win.configure(bg=self.theme["content_bg"])

        self.bar = tk.Frame(win, bg=self.theme["panel"], padx=6, pady=4)
        self.bar.pack(fill="x")
        tk.Button(self.bar, text="⟳", command=self._reload_page, relief="flat",
                  bg=self.theme["accent"], fg=self.theme["content_bg"]).pack(side="right")
        tk.Button(self.bar, text="DevTools", command=self._toggle_devtools, relief="flat",
                  bg=self.theme["panel"], fg=self.theme["fg"]).pack(side="right", padx=4)
        self.url_var = tk.StringVar(value="about:blank")
        entry = tk.Entry(self.bar, textvariable=self.url_var, relief="flat",
                         bg=self.theme["content_bg"], fg=self.theme["fg"])
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self._load_typed())

        self.devtools = tk.Text(win, height=8, bg="#0d0e12", fg="#9ece6a",
                                font=("Consolas", 10), state="disabled")
        self.page_host = tk.Frame(win, bg=self.theme["content_bg"])
        self.page_host.pack(fill="both", expand=True)
        self.current_html = html
        self.errors = 0
        self.err_count = None
        self._toast_widget = None
        self.console = None
        self.js_engine = None
        self.render_preview(html)

    def render_preview(self, html):
        self.current_html = html
        shim = _RenderShim(self)
        ViElectronApp.render_html(shim, html)
        # переносим исполняющее окружение shim'а в окно (для DevTools-логики)
        self.js_engine = shim.js_engine

    def _reload_page(self):
        self.render_preview(self.current_html)

    def _load_typed(self):
        url = self.url_var.get().strip()
        if not url:
            return
        if not url.startswith("http"):
            url = "https://" + url

        def worker():
            try:
                r = requests.get(url, timeout=self.config["network"]["timeout"],
                                 headers={"User-Agent": self.config["network"]["user_agent"]})
                r.encoding = r.encoding or "utf-8"
                self.win.after(0, lambda: self._apply_loaded(url, r.text))
            except Exception as e:
                self.win.after(0, lambda: self.log("engine", "ERROR загрузки: %s" % e))
        if HAVE_REQUESTS:
            threading.Thread(target=worker, daemon=True).start()

    def _apply_loaded(self, url, html):
        self.url_var.set(url)
        self.render_preview(html)

    def inject_css(self, css):
        html = self.current_html
        if "</head>" in html:
            html = html.replace("</head>", "<style>%s</style></head>" % css)
        self.render_preview(html)

    def log(self, channel, message):
        stamp = "%s [%s] %s" % (_now(), channel.upper(), message)
        if "ERROR" in message:
            self.errors += 1
        if self.devtools.winfo_ismapped():
            self.devtools.configure(state="normal")
            self.devtools.insert(tk.END, stamp + "\n")
            self.devtools.see(tk.END)
            self.devtools.configure(state="disabled")

    def toast(self, message):
        if self._toast_widget:
            try:
                self._toast_widget.destroy()
            except tk.TclError:
                pass
        t = tk.Label(self.win, text=str(message), bg="#9ece6a", fg="#14151a",
                     font=("Arial", 11, "bold"), padx=12, pady=6)
        t.place(relx=0.5, rely=0.05, anchor="n")
        self._toast_widget = t
        self.win.after(2500, lambda: t.winfo_exists() and t.destroy())

    def _set_title(self, title):
        self.win.title(title)

    def _close_window(self):
        self.win.destroy()

    def _toggle_devtools(self):
        if self.devtools.winfo_ismapped():
            self.devtools.pack_forget()
        else:
            self.devtools.pack(fill="y", side="bottom")

    def on_config_applied(self, cfg):
        self.config = cfg
        self.theme = THEMES.get(cfg["appearance"]["theme"], THEMES["dark"])
        self.win.title(cfg["window"]["title"])


class _RenderShim(ViElectronApp):
    """Обёртка, позволяющая переиспользовать рендер ViElectronApp внутри
    окна предпросмотра Studio без создания второго Tk root."""

    def __init__(self, owner):
        # Намеренно НЕ вызываем ViElectronApp.__init__ — не создаём tk.Tk().
        self.o = owner
        self.config = owner.config
        self.theme = owner.theme
        self.production = False
        self.start_url = None
        self.start_html = ""
        self.errors = 0
        self.err_count = None
        self.console = None
        self.js_engine = None
        self.page_document = None
        self.msg_queue = queue.Queue()
        self._toast_widget = None
        self.content = _ContentShim(owner)
        self.url_entry = owner.url_var

    # методы моста JS (window.viElectron.*) должны попадать в окно-владелец
    def log(self, channel, message):
        self.o.log(channel, message)

    def toast(self, message):
        self.o.toast(message)

    def _set_title(self, title):
        self.o._set_title(title)

    def _close_window(self):
        self.o._close_window()

    def _console_error(self, message):
        self.o.errors += 1
        self.o.log("js", "ERROR: " + message)

    def load_url(self, url):
        self.o.url_var.set(url)
        self.o._load_typed()


class _ContentShim:
    """Скроллируемая область страницы внутри frame-хоста предпросмотра."""

    def __init__(self, owner):
        self.owner = owner
        host = owner.page_host
        self.canvas = tk.Canvas(host, bg=owner.theme["content_bg"],
                                highlightthickness=0)
        self.vsb = ttk.Scrollbar(host, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=owner.theme["content_bg"])
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self.inner_id, width=e.width))

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()

    def apply_theme(self):
        bg = self.owner.theme["content_bg"]
        self.canvas.configure(bg=bg)
        self.inner.configure(bg=bg)


def load_project(folder):
    folder = Path(folder)
    cfg_path = folder / "package.json"
    html_path = folder / "main.html"
    config = ViElectronApp.default_config()
    if cfg_path.exists():
        user_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        _deep_update(config, user_cfg)
    html = html_path.read_text(encoding="utf-8") if html_path.exists() else DEFAULT_MAIN_HTML
    return config, html


def _deep_update(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v


def simple_prompt(parent, title, label):
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.geometry("320x120")
    tk.Label(dlg, text=label).pack(pady=(12, 4))
    var = tk.StringVar()
    entry = tk.Entry(dlg, textvariable=var, width=32)
    entry.pack()
    result = {"value": None}

    def ok(event=None):
        result["value"] = var.get().strip() or None
        dlg.destroy()

    entry.bind("<Return>", ok)
    tk.Button(dlg, text="OK", command=ok).pack(pady=8)
    entry.focus_set()
    dlg.transient(parent)
    dlg.grab_set()
    parent.wait_window(dlg)
    return result["value"]


def main():
    if "--production" in sys.argv or "--app" in sys.argv:
        folder = Path(__file__).resolve().parent
        config, html = load_project(folder)
        app = ViElectronApp(config=config, start_html=html, production=True)
        app.run()
        return
    studio = ViElectronStudio()
    studio.run()


if __name__ == "__main__":
    main()

