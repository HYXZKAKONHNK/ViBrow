from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
import re
import threading
import tkinter as tk
from tkinter import messagebox
from io import BytesIO
from urllib.parse import parse_qs, quote, urljoin, urlsplit, quote_plus

import requests
from viengine_js import EventTarget, JSEvent, JavaScriptEngine
from viengine_dom import Document, Element, Node, parse_html
from local_cache import LocalCache
from viengine_css import CSSEngine

css_engine = CSSEngine()

try:
  import gif_render
  from PIL import Image, ImageTk
except ImportError:
  Image = None
  ImageTk = None
  gif_render = None


START_PAGE_PATH = Path(__file__).resolve().parent / "resourses" / "vibrow_064.html"
LOCAL_SERVER_PORT = 8765

# 📦 Теги-контейнеры, внутри которых кнопки/ссылки раскладываются по своим
# координатам (горизонтальные меню — в строку, вертикальные списки — столбцом)
LAYOUT_CONTAINER_TAGS = {"nav", "menu", "ul", "ol", "li", "header", "footer", "section", "article", "form", "fieldset"}
MENU_CLASS_NAMES = {"menu", "navbar", "nav", "navigation", "tabs", "tab", "sidebar", "dropdown", "toolbar", "breadcrumb", "breadcrumbs"}


class LocalBridgeServer:

  def __init__(self, start_page, message_queue):
    start_page = Path(start_page).resolve()

    def enqueue_open_url(message):
      if not message.startswith("open_URL="):
        return False
      target_url = message[len("open_URL="):].strip()
      parsed_url = urlsplit(target_url)
      if parsed_url.scheme.lower() not in ("http", "https") or not parsed_url.netloc:
        return False
      message_queue.put(message)
      return True

    class RequestHandler(SimpleHTTPRequestHandler):

      def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(start_page.parent), **kwargs)

      def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

      def log_message(self, format_string, *args):
        pass

      def _send_text(self, status, text):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

      def _handle_message(self, message):
        if enqueue_open_url(message):
          self._send_text(202, "OK")
        else:
          self._send_text(400, "Expected open_URL=https://example.com/")

      def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

      def do_GET(self):
        parsed_request = urlsplit(self.path)
        params = parse_qs(parsed_request.query, keep_blank_values=True)
        if parsed_request.path in ("/message", "/bridge") or (
            parsed_request.path == "/" and ("open_URL" in params or "message" in params)
        ):
          message = params.get("message", [""])[0]
          if not message and "open_URL" in params:
            message = "open_URL=" + params["open_URL"][0]
          self._handle_message(message)
          return

        if parsed_request.path == "/":
          if not start_page.is_file():
            self._send_text(
                200,
              "Стартовая страница не найдена. Возможно она была удалена или перемещена. Пожалуйста, убедитесь, что файл vibrow_064.html в папке resourses существует.",
            )
            return
          self.path = "/" + quote(start_page.name)
        super().do_GET()

      def do_POST(self):
        if urlsplit(self.path).path not in ("/message", "/bridge"):
          self._send_text(404, "Not found")
          return
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > 65536:
          self._send_text(413, "Message too large")
          return
        payload = self.rfile.read(content_length).decode("utf-8", errors="replace").strip()
        content_type = self.headers.get("Content-Type", "").lower()
        if "application/json" in content_type:
          try:
            import json

            data = json.loads(payload)
            payload = data.get("message", "") if isinstance(data, dict) else ""
          except (ValueError, AttributeError):
            payload = ""
        elif "application/x-www-form-urlencoded" in content_type:
          fields = parse_qs(payload, keep_blank_values=True)
          if "open_URL" in fields:
            payload = "open_URL=" + fields["open_URL"][0]
          else:
            payload = fields.get("message", [""])[0]
        self._handle_message(payload)

    self.httpd = ThreadingHTTPServer(
      ("127.0.0.1", LOCAL_SERVER_PORT), RequestHandler
    )
    self.httpd.daemon_threads = True
    self.host, self.port = self.httpd.server_address
    self.url = f"http://{self.host}:{self.port}/"
    self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
    self.thread.start()

  def stop(self):
    self.httpd.shutdown()
    self.httpd.server_close()
    self.thread.join(timeout=1)


class SimpleHTMLParser(HTMLParser):

  def __init__(self):
    super().__init__()
    self.elements = []
    self.current_tag = None
    self.bg_color = "white"
    self.default_font = "Arial"
    self.form_stack = []
    self.forms = {}
    self.form_counter = 0
    self.style_text = ""
    self.css_vars = {}
    self.style_rules = []
    self.stylesheet_urls = []
    self.scripts = []
    self.current_script = None
    self.external_style_text = ""
    self.active_link = None
    self.active_button = None
    self.js_errors = []
    # 🔗 Стек «контейнеров» (меню, навигации, карточки) для layout-координат
    self.container_stack = []
    self.element_containers = {}
    self.dom_order = {}
    self._dom_index = 0

  def _attach_layout_context(self, element_data, tag):
    """Запоминает DOM-родителя элемента — нужно для координат кнопок и меню."""
    self._dom_index += 1
    element_data["dom_order"] = self._dom_index
    parent = None
    for entry in reversed(self.container_stack):
      if entry["end_tag"] == tag:
        continue
      parent = entry
      break
    if parent is not None:
      element_data["parent_dom_id"] = parent["id"]
      self.element_containers[self._dom_index] = parent["id"]

  def _current_form(self):
    if self.form_stack:
      return self.form_stack[-1]
    return {"id": None, "action": "", "method": "get"}

  # 🔧 Эти методы раньше вызывались, но нигде не были определены —
  # любой <a>/<button>/<input> со стилем ронял парсер с AttributeError.
  # Теперь они делегируют в CSSEngine (parse_css_value / resolve_css_color).
  def _parse_css_value(self, style, *keys):
    try:
      return css_engine.parse_css_value(style, *keys)
    except Exception:
      return ""

  def _resolve_css_color(self, value, fallback="white"):
    try:
      return css_engine.resolve_css_color(value, fallback)
    except Exception:
      return fallback

  # 🔧 Аналогично: метод вызывался из handle_data при закрытии <style>,
  # но не был определён — падал на любой странице с инлайн-<style>.
  def _parse_css_vars(self):
    try:
      css_engine.style_text = self.style_text
      css_engine.parse_css_vars()
      self.css_vars = css_engine.css_vars
    except Exception:
      pass

  def _make_element(self, element_data, tag, attr_dict, style, font_family, bg_color):
    """Единая сборка элемента: базовые CSS-поля + layout-контекст (координаты меню)."""
    element_data.setdefault("bg_color", bg_color or self._parse_css_value(style, "background-color"))
    element_data.setdefault("fg_color", self._parse_css_value(style, "color"))
    element_data.setdefault("border_color", self._parse_css_value(style, "border-color", "border"))
    element_data.setdefault("border_radius", self._parse_css_value(style, "border-radius"))
    element_data.setdefault("id", attr_dict.get("id", ""))
    element_data.setdefault("classes", attr_dict.get("class", "").split())
    element_data.setdefault("style", style)
    self._attach_layout_context(element_data, tag)
    self.elements.append(element_data)
    return element_data

  def handle_starttag(self, tag, attrs):
    self.current_tag = tag
    attr_dict = dict(attrs)

    if tag == "script":
      self.current_script = {
          "src": attr_dict.get("src", ""),
          "type": attr_dict.get("type", "").lower(),
          "code": "",
      }
      self.scripts.append(self.current_script)

    style = attr_dict.get("style", "")
    font_family = "Arial"

    # 📦 Контейнеры layout'а: меню, навигация, списки, секции, карточки.
    # Внутри них кнопки и ссылки получают координаты относительно контейнера,
    # а не страницы — это основа полноценного рендеринга.
    if tag in LAYOUT_CONTAINER_TAGS:
      self._dom_index += 1
      display_value = css_engine.parse_css_value(style, "display") or ""
      flex_direction = css_engine.parse_css_value(style, "flex-direction") or ""
      classes = attr_dict.get("class", "").split()
      is_menu_like = (
          tag in ("nav", "menu")
          or any(cls in MENU_CLASS_NAMES for cls in classes)
      )
      horizontal = (
          display_value in ("flex", "inline-flex") and flex_direction != "column"
      ) or is_menu_like or tag == "menu"
      container_entry = {
          "id": self._dom_index,
          "tag": tag,
          "end_tag": tag,
          "horizontal": bool(horizontal),
          "is_menu": bool(is_menu_like),
      }
      self.container_stack.append(container_entry)

    if tag == "link" and "stylesheet" in (attr_dict.get("rel") or "").lower().split():
      if attr_dict.get("href"):
        self.stylesheet_urls.append(attr_dict["href"])

    if "font-family" in style:
      for part in style.split(";"):
        if "font-family" in part and ":" in part:
          raw_font = part.split(":")[1].strip().replace("'", "").replace('"', "")
          if raw_font:
            font_family = raw_font.split(",")[0].strip()

    bg_color = css_engine.detect_background_from_css(self.style_text, default_bg="white")

    if tag == "body":
      body_bg = self._parse_css_value(style, "background", "background-color")
      if body_bg:
        resolved_bg = self._resolve_css_color(body_bg, self.bg_color)
        if resolved_bg:
          self.bg_color = resolved_bg

    if tag == "form":
      action = attr_dict.get("action", "")
      method = (attr_dict.get("method") or "get").lower()
      self.form_counter += 1
      form = {"id": self.form_counter, "action": action, "method": method}
      self.forms[form["id"]] = {**form, "hidden_fields": []}
      self.form_stack.append(form)

    if tag == "input" and attr_dict.get("type", "text").lower() == "hidden":
      form = self._current_form()
      if form["id"] is not None and attr_dict.get("name"):
        self.forms[form["id"]]["hidden_fields"].append(
            (attr_dict["name"], attr_dict.get("value", ""))
        )

    if tag == "input" and attr_dict.get("type", "text").lower() not in ["hidden", "submit", "button", "reset"]:
      form = self._current_form()
      element_data = {
          "tag": "input",
          "text": attr_dict.get("value", ""),
          "placeholder": attr_dict.get("placeholder", ""),
          "input_type": attr_dict.get("type", "text").lower(),
          "selector_tag": "input",
          "name": attr_dict.get("name", ""),
          "id": attr_dict.get("id", ""),
          "classes": attr_dict.get("class", "").split(),
          "style": style,
          "bg_color": self._parse_css_value(style, "background-color", "background"),
          "fg_color": self._parse_css_value(style, "color"),
          "border_color": self._parse_css_value(style, "border-color", "border"),
          "border_radius": self._parse_css_value(style, "border-radius"),
          "form_id": form["id"],
          "action_url": form["action"],
          "method": form["method"],
          "font": font_family,
      }
      self._attach_layout_context(element_data, tag)
      self.elements.append(element_data)

    elif tag == "textarea":
      form = self._current_form()
      element_data = {
          "tag": "textarea",
          "text": "",
          "placeholder": attr_dict.get("placeholder", ""),
          "name": attr_dict.get("name", ""),
          "id": attr_dict.get("id", ""),
          "classes": attr_dict.get("class", "").split(),
          "style": style,
          "selector_tag": "textarea",
          "form_id": form["id"],
          "action_url": form["action"],
          "method": form["method"],
          "font": font_family,
      }
      self._attach_layout_context(element_data, tag)
      self.elements.append(element_data)

    if tag == "img":
      alt_text = "[Изображение]"
      if "alt" in attr_dict:
        alt_text = f"[Картинка: {attr_dict['alt']}]"
      self._make_element({
          "tag": "img",
          "text": alt_text,
          "href": "",
          "src": attr_dict.get("src", ""),
          "font": font_family,
          "action_url": attr_dict.get("src", ""),
          "selector_tag": "img",
      }, tag, attr_dict, style, font_family, bg_color)

    if tag == "a":
      href = attr_dict.get("href", "")
      self.active_link = self._make_element({
          "tag": "a",
          "text": "",
          "href": href,
          "font": font_family,
          "action_url": href,
          "method": "get",
          "selector_tag": "a",
      }, tag, attr_dict, style, font_family, bg_color)

    elif tag == "button":
      form = self._current_form()
      action_url = attr_dict.get("formaction") or form["action"]
      method = (attr_dict.get("formmethod") or form["method"] or "get").lower()
      self.active_button = self._make_element({
          "tag": "button",
          "text": "",
          "href": "",
          "font": font_family,
          "action_url": action_url,
          "method": method,
          "form_id": form["id"],
          "submit": attr_dict.get("type", "submit").lower() not in ["button", "reset"],
          "name": attr_dict.get("name", ""),
          "value": attr_dict.get("value", ""),
          "selector_tag": "button",
      }, tag, attr_dict, style, font_family, bg_color)

    elif tag == "input" and attr_dict.get("type", "").lower() in ["submit", "button"]:
      form = self._current_form()
      input_type = attr_dict.get("type", "").lower()
      action_url = attr_dict.get("formaction") or form["action"]
      method = (attr_dict.get("formmethod") or form["method"] or "get").lower()
      self._make_element({
          "tag": "button",
          "text": attr_dict.get("value") or "Кнопка",
          "href": "",
          "font": font_family,
          "action_url": action_url,
          "method": method,
          "form_id": form["id"],
          "submit": input_type == "submit",
          "name": attr_dict.get("name", ""),
          "value": attr_dict.get("value", ""),
          "input_type": input_type,
          "selector_tag": "input",
      }, tag, attr_dict, style, font_family, bg_color)
    else:
      self.default_font = font_family

  def handle_endtag(self, tag):
    if tag == "script":
      self.current_script = None
      self.current_tag = None
    if tag == "form" and self.form_stack:
      self.form_stack.pop()
    if tag == "textarea":
      self.current_tag = None
    if tag == "style":
      self.bg_color = css_engine.detect_background_from_css(self.style_text, default_bg="white")
    if tag in ["a", "body"]:
      self.current_tag = None
    if tag == "a":
      self.active_link = None
    if tag == "button":
      self.active_button = None

  def handle_data(self, data):
    if self.current_tag == "script" and self.current_script is not None:
      self.current_script["code"] += data
      return

    if self.current_tag == "textarea" and self.elements and self.elements[-1]["tag"] == "textarea":
      self.elements[-1]["text"] += data
      return

    cleaned = data.strip()
    if not cleaned:
      return

    if self.active_link is not None:
      self.active_link["text"] = (self.active_link["text"] + " " + cleaned).strip()
      return
    if self.active_button is not None:
      self.active_button["text"] = (self.active_button["text"] + " " + cleaned).strip()
      return

    if self.current_tag == "style":
      self.style_text += data
      self._parse_css_vars()
      return

    if self.current_tag in ["head"]:
      return

    current_font = getattr(self, "default_font", "Arial")

    if self.current_tag == "a" and self.elements and self.elements[-1]["tag"] == "a":
      self.elements[-1]["text"] = cleaned
    elif self.current_tag == "button" and self.elements and self.elements[-1]["tag"] == "button":
      self.elements[-1]["text"] = cleaned
    else:
      self.elements.append(
          {
              "tag": self.current_tag if self.current_tag else "p",
              "text": cleaned,
              "href": "",
              "font": current_font,
          }
      )
    self.default_font = "Arial"

class SimpleBrowser:

  def __init__(self, root):
    self.root = root
    self.root.title("Vibrow")
    self.root.geometry("800x600")
    self._set_window_icon()
    self.session = requests.Session()
    self.session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Ch-Ua": (
            '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'
        ),
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    })
    self.cache = LocalCache()
    self.bridge_messages = Queue()
    self.bridge_server = LocalBridgeServer(
        START_PAGE_PATH, self.bridge_messages
    )
    self.active_gifs = []
    try:
      self.root.state("zoomed")
    except tk.TclError:
      pass

    self.tabs = [{"url": self.bridge_server.url, "icon": None}]
    self.active_tab = 0
    self.favicon_cache = {}
    self.tab_frame = tk.Frame(root, bg="#e0e0e0")
    self.tab_frame.pack(fill=tk.X, padx=5, pady=(5, 0))
    self._render_tabs()

    top_frame = tk.Frame(root, bg="#e0e0e0", height=50)
    top_frame.pack(fill=tk.X, padx=5, pady=(3, 5))

    # 🌟 ТЕПЕРЬ ВСЁ С РО В Н Ы М И ОТСТУПАМИ ВНУТРИ __init__!
    self.header_gif_canvas = tk.Canvas(
        top_frame, width=32, height=32, bg="#e0e0e0", highlightthickness=0
    )
    self.header_gif_canvas.pack(side=tk.LEFT, padx=(5, 5))

    # 🎬 Если модуль gif_render подключен — запускаем гифку!
    if gif_render:
      import os
      from pathlib import Path

      gif_path = (
          Path(__file__).resolve().parent / "resourses" / "Vibrow_anim.gif"
      )  # Путь к гифке!
      if os.path.exists(gif_path):
        self.header_gif = gif_render.CustomHeaderRenderer(
            self.header_gif_canvas, str(gif_path)
        )
        self.header_gif.start()

    address_bar = tk.Canvas(
        top_frame, height=42, bg="#e0e0e0", highlightthickness=0
    )
    address_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
    self.url_entry = tk.Entry(
        address_bar,
        font=("Arial", 14),
        relief=tk.FLAT,
        bd=0,
        bg="#ffffff",
        fg="#202124",
        insertbackground="#202124",
    )
    self.url_placeholder = "Введите запрос или URL"
    address_entry_id = address_bar.create_window(
      14, 21, anchor="w", width=200, height=30, window=self.url_entry
    )

    def draw_address_bar(event):
      width = max(event.width, 60)
      address_bar.delete("address-bg")
      address_bar.create_rectangle(
        20, 1, width - 20, 41, fill="#ffffff", outline="", tags="address-bg"
      )
      address_bar.create_rectangle(
        1, 20, width - 1, 22, fill="#ffffff", outline="", tags="address-bg"
      )
      for x1 in (1, width - 41):
        address_bar.create_oval(
            x1, 1, x1 + 40, 41, fill="#ffffff", outline="", tags="address-bg"
        )
      address_bar.create_arc(
        1, 1, 41, 41, start=90, extent=90, style=tk.ARC,
        outline="#cfd5dd", width=1, tags="address-bg",
      )
      address_bar.create_arc(
        width - 41, 1, width - 1, 41, start=0, extent=90, style=tk.ARC,
        outline="#cfd5dd", width=1, tags="address-bg",
      )
      address_bar.create_arc(
        1, 1, 41, 41, start=180, extent=90, style=tk.ARC,
        outline="#cfd5dd", width=1, tags="address-bg",
      )
      address_bar.create_arc(
        width - 41, 1, width - 1, 41, start=270, extent=90, style=tk.ARC,
        outline="#cfd5dd", width=1, tags="address-bg",
      )
      address_bar.coords(address_entry_id, 14, 21)
      address_bar.itemconfigure(address_entry_id, width=max(width - 28, 40))
      address_bar.tag_lower("address-bg")

    address_bar.bind("<Configure>", draw_address_bar)
    self.url_entry.insert(0, self.url_placeholder)
    self.url_entry.config(fg="#a6a6a6")
    self.url_entry.bind("<FocusIn>", self._clear_url_placeholder)
    self.url_entry.bind("<FocusOut>", self._restore_url_placeholder)
    self.url_entry.bind("<KeyPress>", self._clear_url_placeholder)
    self.url_entry.bind("<Return>", lambda event: self.load_page())

    go_button = tk.Canvas(
      top_frame, width=42, height=42, bg="#e0e0e0",
      highlightthickness=0, cursor="hand2",
    )
    go_button.pack(side=tk.RIGHT)
    icon_center = 21
    icon_radius = 18
    for step in range(36):
      offset = -icon_radius + (step + 0.5) * (2 * icon_radius / 36)
      half_height = (icon_radius ** 2 - offset ** 2) ** 0.5
      blend = step / 35
      red = int(52 + (239 - 52) * blend)
      green = int(120 + (68 - 120) * blend)
      blue = int(246 + (88 - 246) * blend)
      go_button.create_line(
        icon_center + offset, icon_center - half_height,
        icon_center + offset, icon_center + half_height,
        fill="#{:02x}{:02x}{:02x}".format(red, green, blue), width=2,
      )
    go_button.create_oval(
      3, 3, 39, 39, outline="#ffffff", width=2
    )
    go_button.create_oval(
      12, 11, 25, 24, outline="#ffffff", width=2
    )
    go_button.create_line(
      24, 23, 31, 30, fill="#ffffff", width=3, capstyle=tk.ROUND
    )
    go_button.bind("<Button-1>", lambda event: self.load_page())

    # Создаем контейнер для холста и полосы прокрутки
    canvas_container = tk.Frame(root)
    canvas_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    self.canvas = tk.Canvas(canvas_container, bg="white", highlightthickness=0)
    v_scrollbar = tk.Scrollbar(canvas_container, orient=tk.VERTICAL, command=self.canvas.yview)
    self.canvas.configure(yscrollcommand=v_scrollbar.set)

    v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # Поддержка прокрутки колесиком мыши
    def _on_mousewheel(event):
      self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # Привязываем колесико мыши ко всему окну
    self.canvas.bind_all("<MouseWheel>", _on_mousewheel)

    self.links = []
    self.image_refs = []
    self.page_widgets = []
    self.form_fields = []
    self.page_forms = {}
    self.canvas.bind("<Motion>", self._update_link_cursor)
    self.canvas.bind("<Leave>", lambda event: self.canvas.configure(cursor=""))
    self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    self.root.bind("<Control-Delete>", lambda e: self.clear_all_cache())
    self.root.after(100, self._poll_bridge_messages)
    self.root.after(250, self._load_start_page)

  def _set_window_icon(self):
    from pathlib import Path

    resources = Path(__file__).resolve().parent / "resourses"
    icon_path = resources / "ViBrow_logo.ico"
    try:
      self.root.iconbitmap(str(icon_path))
    except tk.TclError:
      pass
    try:
      self.window_icon = tk.PhotoImage(file=str(resources / "ViBrow_logo.png"))
      self.root.iconphoto(True, self.window_icon)
    except tk.TclError:
      self.window_icon = None

    try:
      import ctypes
      from ctypes import wintypes

      user32 = ctypes.WinDLL("user32", use_last_error=True)
      load_image = user32.LoadImageW
      load_image.argtypes = (
          wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
          ctypes.c_int, ctypes.c_int, wintypes.UINT,
      )
      load_image.restype = wintypes.HANDLE
      icon_handle = load_image(None, str(icon_path), 1, 0, 0, 0x10)
      if icon_handle:
        self.root.update_idletasks()
        send_message = user32.SendMessageW
        send_message.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        )
        send_message.restype = ctypes.c_ssize_t
        hwnd = self.root.winfo_id()
        send_message(hwnd, 0x80, 0, icon_handle)
        send_message(hwnd, 0x80, 1, icon_handle)
        self.native_icon_handle = icon_handle
    except (AttributeError, OSError, tk.TclError):
      self.native_icon_handle = None

  def _update_link_cursor(self, event):
    over_link = any(
        link["x1"] <= event.x <= link["x2"]
        and link["y1"] <= event.y <= link["y2"]
        for link in self.links
    )
    self.canvas.configure(cursor="hand2" if over_link else "")

  def _poll_bridge_messages(self):
    while True:
      try:
        message = self.bridge_messages.get_nowait()
      except Empty:
        break
      if message.startswith("open_URL="):
        target_url = message[len("open_URL="):].strip()
        self._set_address_text(target_url)
        self.load_page()
    if self.root.winfo_exists():
      self.root.after(100, self._poll_bridge_messages)

  def _load_start_page(self):
    self._set_address_text(self.bridge_server.url)
    self.load_page()
    self.url_entry.delete(0, tk.END)
    self.url_entry.insert(0, self.url_placeholder)
    self.url_entry.config(fg="#a6a6a6")

  def _on_close(self):
    if hasattr(self, "header_gif") and self.header_gif:
      self.header_gif.stop()  
    self.bridge_server.stop()
    self.root.destroy()

  def _set_address_text(self, text):
    self.url_entry.delete(0, tk.END)
    self.url_entry.insert(0, text)
    self.url_entry.config(fg="#202124")

  def _clear_url_placeholder(self, event=None):
    if self.url_entry.get() == self.url_placeholder:
      self.url_entry.delete(0, tk.END)
      self.url_entry.config(fg="#202124")

  def _restore_url_placeholder(self, event=None):
    if not self.url_entry.get().strip():
      self.url_entry.insert(0, self.url_placeholder)
      self.url_entry.config(fg="#a6a6a6")

  def _tab_title(self, url):
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "Новая вкладка").removeprefix("www.")
    return host.split(".", 1)[0].capitalize()

  def _load_favicon(self, url):
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if not parts.netloc:
      return None
    host = parts.netloc.lower()
    if host in self.favicon_cache:
      return self.favicon_cache[host]

    icon = None
    if Image is not None and ImageTk is not None:
      try:
        icon_url = f"{parts.scheme}://{parts.netloc}/favicon.ico"
        response = self.session.get(icon_url, timeout=2)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        image.thumbnail((16, 16))
        icon = ImageTk.PhotoImage(image)
      except Exception:
        pass
    self.favicon_cache[host] = icon
    return icon

  def _render_tabs(self):
    for widget in self.tab_frame.winfo_children():
      widget.destroy()

    for index, tab in enumerate(self.tabs):
      selected = index == self.active_tab
      bg = "#ffffff" if selected else "#d4d8de"
      tab_widget = tk.Frame(self.tab_frame, bg=bg, padx=4, pady=2)
      tab_widget.pack(side=tk.LEFT, padx=(0, 3), pady=(2, 0))
      icon = tab.get("icon")
      if icon:
        icon_label = tk.Label(tab_widget, image=icon, bg=bg, cursor="hand2")
        icon_label.pack(side=tk.LEFT, padx=(2, 4))
      else:
        icon_canvas = tk.Canvas(
            tab_widget, width=18, height=18, bg=bg,
            highlightthickness=0, cursor="hand2",
        )
        icon_canvas.pack(side=tk.LEFT, padx=(2, 4))
        title = self._tab_title(tab["url"])
        shade = sum(ord(char) for char in title) % 80
        color = "#{:02x}{:02x}{:02x}".format(70 + shade, 100, 170)
        icon_canvas.create_oval(1, 1, 17, 17, fill=color, outline="")
        icon_canvas.create_text(
            9, 9, text=title[:1].upper(), fill="#ffffff", font=("Arial", 9, "bold")
        )
        icon_canvas.bind(
            "<Button-1>", lambda event, target=index: self._switch_tab(target)
        )
      if icon:
        icon_label.bind(
            "<Button-1>", lambda event, target=index: self._switch_tab(target)
        )
      tk.Button(
          tab_widget, text=self._tab_title(tab["url"])[:22],
          command=lambda target=index: self._switch_tab(target),
          relief=tk.FLAT, bg=bg, activebackground=bg, bd=0,
          padx=3, pady=2, font=("Arial", 10),
      ).pack(side=tk.LEFT)
      tk.Button(
          tab_widget, text="x", width=2,
          command=lambda target=index: self._close_tab(target),
          relief=tk.FLAT, bg=bg, activebackground=bg, bd=0,
          padx=0, pady=1, font=("Arial", 9),
      ).pack(side=tk.LEFT)

    tk.Button(
        self.tab_frame, text="+", command=self._new_tab,
        relief=tk.FLAT, bg="#e0e0e0", activebackground="#ffffff",
        bd=0, padx=10, pady=2, font=("Arial", 13),
    ).pack(side=tk.LEFT, pady=(1, 0))

  def _update_active_tab(self, url):
    self.tabs[self.active_tab]["url"] = url
    self.tabs[self.active_tab]["icon"] = self._load_favicon(url)
    self._render_tabs()

  def _switch_tab(self, index):
    if index == self.active_tab:
      return
    self.active_tab = index
    self._set_address_text(self.tabs[index]["url"])
    self._render_tabs()
    self.load_page()

  def _new_tab(self):
    self.tabs.append({"url": "https://vivweb.vercel.app/", "icon": None})
    self.active_tab = len(self.tabs) - 1
    self._set_address_text(self.tabs[self.active_tab]["url"])
    self._render_tabs()
    self.load_page()

  def _close_tab(self, index):
    was_active = index == self.active_tab
    self.tabs.pop(index)
    if not self.tabs:
      self.tabs.append({"url": "https://vivweb.vercel.app/", "icon": None})
      self.active_tab = 0
    elif index < self.active_tab:
      self.active_tab -= 1
    elif was_active:
      self.active_tab = min(index, len(self.tabs) - 1)
    self._set_address_text(self.tabs[self.active_tab]["url"])
    self._render_tabs()
    self.load_page()

  def _clear_page_widgets(self):
    for gif in getattr(self, "active_gifs", []):
      if hasattr(gif, "stop"):
        gif.stop()
    self.active_gifs = []
    for widget in self.page_widgets:
      widget.destroy()
    self.page_widgets = []

  def _set_placeholder(self, widget, placeholder, multiline=False):
    if not placeholder:
      return

    start = "1.0" if multiline else 0
    end = "end-1c" if multiline else tk.END
    widget.insert(start, placeholder)
    widget.config(fg="#777777")

    def clear_placeholder(event):
      current = widget.get("1.0", "end-1c") if multiline else widget.get()
      if current == placeholder:
        widget.delete("1.0", tk.END) if multiline else widget.delete(0, tk.END)
        widget.config(fg="#111111")

    def restore_placeholder(event):
      current = widget.get("1.0", "end-1c") if multiline else widget.get()
      if not current:
        widget.insert(start, placeholder)
        widget.config(fg="#777777")

    widget.bind("<FocusIn>", clear_placeholder)
    widget.bind("<FocusOut>", restore_placeholder)
    widget.bind("<KeyPress>", clear_placeholder)

  def _resolve_url(self, base_url, target_url):
    if not target_url:
      return ""
    if target_url.startswith("//"):
      return "https:" + target_url
    if target_url.startswith("/"):
      return urljoin(base_url, target_url)
    if target_url.startswith("http"):
      return target_url
    return urljoin(base_url.rstrip("/") + "/", target_url)

  def _normalize_color(self, value, fallback="white"):
    if not value:
      return fallback
    value = str(value).strip().replace("!important", "")
    if not value:
      return fallback
    if value.lower() == "transparent":
      return fallback
    if value.startswith("#"):
      raw = value
      if len(raw) in (4, 5):
        raw = "#" + "".join(ch * 2 for ch in raw[1:])
      if len(raw) == 9:
        raw = raw[:7]
      if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw.lower()
      if re.fullmatch(r"#[0-9a-fA-F]{3}", raw):
        return "#" + "".join(ch * 2 for ch in raw[1:]).lower()
    if re.fullmatch(r"rgba?\(.*\)", value, flags=re.IGNORECASE):
      match = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)", value, flags=re.IGNORECASE)
      if match:
        r, g, b = [int(float(part)) for part in match.groups()[:3]]
        return "#{:02x}{:02x}{:02x}".format(r, g, b)
    if re.fullmatch(r"var\(\s*--[a-zA-Z0-9_-]+\s*\)", value):
      return fallback
    if re.fullmatch(r"[a-zA-Z]+", value):
      return value.lower()
    return fallback

  def _border_radius_pixels(self, value):
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*(px|rem|em|%)?", str(value or ""))
    if not match:
      return 0
    radius = float(match.group(1))
    if match.group(2) in ("rem", "em"):
      radius *= 16
    elif match.group(2) == "%":
      radius = 1000
    return radius

  def _draw_rounded_button(self, x1, y1, x2, y2, bg_color, text_color, border_color, radius=12, text="", font=("Arial", 11, "bold"), canvas=None):
    canvas = canvas or self.canvas
    radius = min(radius, max((x2 - x1) / 2, 2), max((y2 - y1) / 2, 2))
    r = int(radius)

    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=bg_color, outline=border_color, width=1)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=bg_color, outline=border_color, width=1)
    canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="pieslice", fill=bg_color, outline=border_color, width=1)
    canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="pieslice", fill=bg_color, outline=border_color, width=1)
    canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="pieslice", fill=bg_color, outline=border_color, width=1)
    canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="pieslice", fill=bg_color, outline=border_color, width=1)

    canvas.create_text(
        (x1 + x2) / 2,
        (y1 + y2) / 2,
        text=text[:40],
        anchor="center",
        font=font,
        fill=text_color,
    )

  def _load_image(self, image_url):
    if not image_url or Image is None or ImageTk is None:
      return None

    try:
      resolved_url = self._resolve_url(self.url_entry.get(), image_url)
      response = self.session.get(resolved_url, timeout=10)
      response.raise_for_status()

      image = Image.open(BytesIO(response.content))
      image = image.convert("RGBA")
      max_w = 220
      max_h = 180
      image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
      return ImageTk.PhotoImage(image)
    except Exception:
      return None

  def _looks_like_search_page(self, parser, base_url):
    text_blob = " ".join(el.get("text", "") for el in parser.elements if el.get("text"))
    lower = (base_url + " " + text_blob).lower()
    markers = ["google", "search", "images", "youtube", "bing", "q="]
    return any(marker in lower for marker in markers)

  def render_search_shell(self, parser, base_url):
    self.canvas.delete("all")
    self._clear_page_widgets()
    self.links = []
    self.image_refs = []

    canvas_width = self.canvas.winfo_width() or 800
    canvas_height = self.canvas.winfo_height() or 600
    page_bg = "#ffffff"
    self.root.configure(bg=page_bg)
    self.canvas.config(bg=page_bg)
    self.canvas.create_rectangle(0, 0, canvas_width, canvas_height, fill=page_bg, outline="")

    google_text = "Google"
    colors = ["#4285F4", "#EA4335", "#FBBC05", "#4285F4", "#34A853", "#EA4335"]
    x = 24
    for idx, ch in enumerate(google_text):
      self.canvas.create_text(x + idx * 14, 34, text=ch, font=("Arial", 22, "bold"), fill=colors[idx], anchor="w")

    tab_y = 62
    tabs = ["Поиск", "Картинки", "Видео"]
    for idx, tab in enumerate(tabs):
      bx = 200 + idx * 100
      self.canvas.create_rectangle(bx, tab_y, bx + 90, tab_y + 32, fill="#f3f5f7" if idx == 0 else "#ffffff", outline="#dfe5eb", width=1)
      self.canvas.create_text(bx + 45, tab_y + 16, text=tab, anchor="center", fill="#3c4043", font=("Arial", 10, "bold"))

    search_box_y = 110
    search_left = 190
    search_right = canvas_width - 24
    button_center_x = search_right - 25
    button_center_y = search_box_y + 25
    button_radius = 19
    self.canvas.create_rectangle(
      search_left + 24, search_box_y, search_right - 24, search_box_y + 50,
      fill="#ffffff", outline="#dfe5eb", width=1
    )
    self.canvas.create_rectangle(
      search_left, search_box_y + 24, search_right, search_box_y + 26,
      fill="#ffffff", outline="#ffffff"
    )
    for corner_x, corner_y, start_angle in [
      (search_left, search_box_y, 90),
      (search_right - 48, search_box_y, 0),
      (search_left, search_box_y + 2, 180),
      (search_right - 48, search_box_y + 2, 270),
    ]:
      self.canvas.create_arc(
        corner_x, corner_y, corner_x + 48, corner_y + 48,
        start=start_angle, extent=90, style=tk.ARC,
        outline="#dfe5eb", width=1
      )
    search_entry = tk.Entry(
      self.canvas, font=("Arial", 12), relief=tk.FLAT,
      bg="#ffffff", fg="#202124", insertbackground="#202124",
    )
    search_entry.insert(0, self._search_query(base_url))
    search_entry.icursor(tk.END)
    search_entry.bind("<Return>", lambda event: self._submit_search(search_entry.get(), base_url))
    self.canvas.create_window(
      search_left + 18, search_box_y + 9, anchor="nw",
      width=max(button_center_x - search_left - 48, 100), height=32,
      window=search_entry,
    )
    self.page_widgets.append(search_entry)

    gradient_steps = 38
    for step in range(gradient_steps):
      offset = -button_radius + (step + 0.5) * (2 * button_radius / gradient_steps)
      half_height = (button_radius ** 2 - offset ** 2) ** 0.5
      blend = step / (gradient_steps - 1)
      red = int(52 + (239 - 52) * blend)
      green = int(120 + (68 - 120) * blend)
      blue = int(246 + (88 - 246) * blend)
      stripe_color = "#{:02x}{:02x}{:02x}".format(red, green, blue)
      stripe_x = button_center_x + offset
      self.canvas.create_line(
        stripe_x, button_center_y - half_height,
        stripe_x, button_center_y + half_height,
        fill=stripe_color, width=2,
      )
    self.canvas.create_oval(
      button_center_x - button_radius, button_center_y - button_radius,
      button_center_x + button_radius, button_center_y + button_radius,
      outline="#ffffff", width=2,
    )
    self.canvas.create_oval(
      button_center_x - 7, button_center_y - 8,
      button_center_x + 5, button_center_y + 4,
      outline="#ffffff", width=2,
    )
    self.canvas.create_line(
      button_center_x + 4, button_center_y + 3,
      button_center_x + 10, button_center_y + 9,
      fill="#ffffff", width=3, capstyle=tk.ROUND,
    )

    results = []
    image_index = 0
    for el in parser.elements:
      text = (el.get("text") or "").strip()
      if text:
        results.append(text)
      if el.get("tag") == "img" and image_index < 3:
        image_url = el.get("src") or el.get("action_url", "")
        image = self._load_image(image_url)
        if image:
          self.image_refs.append(image)
          self.canvas.create_image(24 + image_index * 120, 180, anchor="nw", image=image)
          image_index += 1

    y_offset = 180 + 90 if image_index else 180
    for index, result in enumerate(results[:10]):
      self.canvas.create_rectangle(20, y_offset, canvas_width - 20 , y_offset + 42, fill="#ffffff", outline="#eef2f7", width=1)
      self.canvas.create_text(32, y_offset + 14, text=result[:80], anchor="w", fill="#1a0dab" if index % 2 == 0 else "#2d5be3", font=("Arial", 11, "bold"))
      y_offset += 50

    def handle_search_canvas_click(event):
      if (
          button_center_x - button_radius <= event.x <= button_center_x + button_radius
          and button_center_y - button_radius <= event.y <= button_center_y + button_radius
      ):
        self._submit_search(search_entry.get(), base_url)
      else:
        self.on_canvas_click(event)

    self.canvas.bind("<Button-1>", handle_search_canvas_click)
    self.canvas.configure(scrollregion=(0, 0, canvas_width, y_offset + 50))

  def render_generic_page(self, parser):
    self.canvas.delete("all")
    self._clear_page_widgets()
    self.links = []
    self.image_refs = []
    self.form_fields = []
    self.page_forms = parser.forms
    self.page_document = getattr(parser, "dom_document", None)
    self.page_external_style_text = getattr(parser, "external_style_text", "")

    page_bg = self._normalize_color(parser.bg_color, "white")
    self.root.configure(bg=page_bg)
    self.canvas.config(bg=page_bg)
    canvas_width = self.canvas.winfo_width()
    canvas_height = self.canvas.winfo_height()
    self.canvas.create_rectangle(
        0, 0, canvas_width, canvas_height, fill=page_bg, outline=""
    )
    self.canvas.create_rectangle(
        12, 12, canvas_width - 12, canvas_height - 12,
        fill=page_bg, outline="#dfe5eb", width=1
    )

    y_offset = 24
    for index, el in enumerate(parser.elements):

      tag = el["tag"]
      text = el["text"]
      href = el.get("href", "")
      site_font = el.get("font", "Arial")

      if tag in ["input", "textarea"]:
        field_width = max(canvas_width - 70, 200)
        field_height = 90 if tag == "textarea" else 30
        field_radius = self._border_radius_pixels(el.get("border_radius"))
        field_bg = self._normalize_color(el.get("bg_color"), "#ffffff")
        field_fg = self._normalize_color(el.get("fg_color"), "#202124")
        field_border = self._normalize_color(el.get("border_color"), "#999999")
        field_canvas = None
        field_parent = self.canvas
        if field_radius > 0:
          field_canvas = tk.Canvas(
              self.canvas, width=field_width, height=field_height,
              bg=page_bg, highlightthickness=0,
          )
          field_parent = field_canvas
        if tag == "textarea":
          field = tk.Text(
              field_parent, font=(site_font, 11), height=4, wrap=tk.WORD,
              relief=tk.FLAT if field_canvas else tk.SOLID,
              borderwidth=0 if field_canvas else 1, bg=field_bg, fg=field_fg,
          )
          if text:
            field.insert("1.0", text)

        else:
          field = tk.Entry(
              field_parent, font=(site_font, 11),
              relief=tk.FLAT if field_canvas else tk.SOLID,
              borderwidth=0 if field_canvas else 1, bg=field_bg, fg=field_fg,
              insertbackground=field_fg,
          )
          if text:
            field.insert(0, text)
        self._set_placeholder(field, el.get("placeholder", ""), multiline=tag == "textarea")
        form_id = el.get("form_id")
        field_name = el.get("name", "")
        field_metadata = {
            "widget": field,
            "form_id": form_id,
            "name": field_name,
          "input_type": el.get("input_type", "text"),
            "placeholder": el.get("placeholder", ""),
            "multiline": tag == "textarea",
        }
        self.form_fields.append(field_metadata)
        field.bind(
            "<Return>",
          lambda event, target=field, target_form=form_id,
          target_type=field_metadata["input_type"], target_name=field_name:
          self._handle_field_enter(
            target, target_form, target_type, target_name
          ),
        )
        if tag == "textarea":
          field.bind(
              "<Shift-Return>",
              lambda event, target=field: (target.insert("insert", "\n"), "break")[1],
          )
        if field_canvas:
          self._draw_rounded_button(
              0, 0, field_width, field_height,
              bg_color=field_bg, text_color=field_fg,
              border_color=field_border, radius=field_radius,
              text="", canvas=field_canvas,
          )
          field_canvas.create_window(
              8, field_height / 2, anchor="w",
              width=max(field_width - 16, 40),
              height=field_height - 8, window=field,
          )
          self.canvas.create_window(
              20, y_offset, anchor="nw", width=field_width,
              height=field_height, window=field_canvas,
          )
          self.page_widgets.append(field_canvas)
        else:
          self.canvas.create_window(
              20, y_offset, anchor="nw", width=field_width,
              height=field_height, window=field,
          )
          self.page_widgets.append(field)
        y_offset += 100 if tag == "textarea" else 40
        continue

      if index > 0:
        self.canvas.create_line(
            24, y_offset - 8, canvas_width - 24, y_offset - 8,
            fill="#dfe5eb", width=1
        )

      if tag == "img":
        image_url = el.get("src") or el.get("action_url", "")
        loaded_image = self._load_image(image_url)
        if image_url.lower().endswith(".gif") and gif_render:
          gif_player = gif_render.GIFRender(self.canvas, image_url, x=20, y=y_offset)
          gif_player.start()
          self.active_gifs.append(gif_player)
          y_offset += 150
          continue

        if loaded_image:
          self.image_refs.append(loaded_image)
          self.canvas.create_image(20, y_offset, anchor="nw", image=loaded_image)
          caption = text.replace("[Картинка: ", "").rstrip("]") if text.startswith("[Картинка:") else text
          if caption:
            self.canvas.create_text(
                20,
                y_offset + 110,
                text=caption[:80],
                anchor="nw",
                font=(site_font, 10, "italic"),
                fill="#555555",
            )
          y_offset += 150
          continue

      if not text:
        continue

      try:
        if tag in ["h1", "h2", "h3"]:
          font = (site_font, 16, "bold")
          color = "#000080"
          indent = 20
        elif tag in ["button", "a"]:
          font = (site_font, 12, "bold")
          color = el.get("fg_color") or "#0066cc"
          indent = 30
        else:
          font = (site_font, 11)
          color = "black"
          indent = 20
      except Exception:
        font = ("Arial", 11)
        color = "black"
        indent = 20

      x1, y1 = indent - 5, y_offset - 2
      x2, y2 = indent + len(text) * 7 + 10, y_offset + 20

      if tag == "button":
        button_fill = self._normalize_color(el.get("bg_color"), "#efefef")
        border_color = self._normalize_color(el.get("border_color"), "#a6a6a6")
        text_color = self._normalize_color(el.get("fg_color"), "#202124")
        button_radius = self._border_radius_pixels(el.get("border_radius"))
        x1, y1 = indent - 5, y_offset - 6
        x2, y2 = indent + max(len(text) * 7 + 20, 110), y_offset + 28
        self._draw_rounded_button(
            x1, y1, x2, y2,
            bg_color=button_fill,
            text_color=text_color,
            border_color=border_color,
            radius=button_radius,
            text=text[:40],
            font=(site_font, 11, "bold"),
        )
      else:
        block_x1 = 18
        block_x2 = canvas_width - 18
        self.canvas.create_rectangle(
            block_x1, y_offset - 10, block_x2, y_offset + 18,
            fill="#ffffff", outline="#eef2f7", width=1
        )
        self.canvas.create_text(
            indent, y_offset, text=text[:80], anchor="nw", font=font, fill=color
        )

      if tag in ["button", "a"]:
        self.links.append({
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "text": text,
            "href": href,
            "action_url": el.get("action_url", href),
            "method": el.get("method", "get"),
            "tag": tag,
            "element_id": el.get("id", ""),
            "form_id": el.get("form_id"),
            "submit": el.get("submit", True),
            "name": el.get("name", ""),
            "value": el.get("value", ""),
        })

      if tag != "button":
        y_offset += 30
      else:
        y_offset += 45

    self.canvas.bind("<Button-1>", self.on_canvas_click)
    self.canvas.configure(scrollregion=(0, 0, canvas_width, y_offset + 50))

  def render_html(self, html_text, base_url):
    parser = SimpleHTMLParser()
    parser.feed(html_text)
    parser.dom_document = parse_html(html_text, base_url)
    for stylesheet_url in parser.stylesheet_urls[:3]:
      try:
        response = self.session.get(
            self._resolve_url(base_url, stylesheet_url), timeout=2
        )
        response.raise_for_status()
        parser.external_style_text += "\n" + response.text
      except Exception:
        continue
    self._execute_page_scripts(parser, base_url)
    self.render_generic_page(self._renderer_parser(parser))

  def _renderer_parser(self, parser):
    document = getattr(parser, "dom_document", None)
    if not isinstance(document, Document):
      return parser
    rendered_parser = SimpleHTMLParser()
    rendered_parser.feed(document.to_html())
    rendered_parser.dom_document = document
    rendered_parser.external_style_text = parser.external_style_text
    rendered_parser.style_text += parser.external_style_text
    rendered_parser.js_errors = parser.js_errors
    rendered_parser.bg_color = css_engine.detect_background_from_css(rendered_parser.style_text, default_bg="white")
    css_engine.apply_css_styles(rendered_parser) # Если твоя библиотека умеет применять стили к элементам
    return rendered_parser

  def _execute_page_scripts(self, parser, base_url):
    from urllib.parse import urljoin

    sources = []
    for script in parser.scripts:
      script_type = script["type"].split(";", 1)[0].strip()
      if script_type and script_type not in (
          "text/javascript", "application/javascript", "module"
      ):
        continue
      source = script["code"]
      if script["src"]:
        try:
          response = self.session.get(
              urljoin(base_url, script["src"]), timeout=3
          )
          response.raise_for_status()
          source = response.text
        except Exception as exc:
          parser.js_errors.append(f"{script['src']}: {exc}")
          continue
      if source.strip():
        if len(source) > 262144:
          parser.js_errors.append("JavaScript script skipped: source exceeds 256 KB")
          continue
        sources.append(source)
    if not sources:
      return

    written_html = []
    written_count = [0]
    rendered = [False]
    engine = JavaScriptEngine()
    document = getattr(parser, "dom_document", None) or EventTarget()
    window = EventTarget()
    document.readyState = "loading"
    original_write = getattr(document, "write", None)
    original_writeln = getattr(document, "writeln", None)

    def document_write(*parts):
      markup = "".join(map(str, parts))
      written_html.append(markup)
      if original_write:
        original_write(markup)

    def document_writeln(*parts):
      markup = "".join(map(str, parts)) + "\n"
      written_html.append(markup)
      if original_writeln:
        original_writeln(markup)

    document.write = document_write
    document.writeln = document_writeln
    window.document = document
    window.location = {"href": base_url}
    window.innerWidth = self.canvas.winfo_width()
    window.innerHeight = self.canvas.winfo_height()
    if isinstance(document, Document):
      document.defaultView = window
      document.location = window.location
    window.setTimeout = lambda callback, delay=0, *args: engine.event_loop.set_timeout(
      lambda: callback(*args), delay
    )
    window.clearTimeout = engine.event_loop.clear_timer
    window.setInterval = lambda callback, delay=0, *args: engine.event_loop.set_timeout(
      lambda: callback(*args), delay, max(1, float(delay))
    )
    window.clearInterval = engine.event_loop.clear_timer
    window.requestAnimationFrame = lambda callback: engine.event_loop.set_timeout(
      lambda: callback(engine.event_loop.now), 16
    )
    console = {name: (lambda *args: None) for name in ("log", "info", "warn", "error", "debug")}

    def flush_written_html(force=False):
      if written_count[0] == len(written_html) and not force:
        return
      written_count[0] = len(written_html)
      if rendered[0]:
        self.render_generic_page(self._renderer_parser(parser))

    def schedule_timer(timer_id, delay):
      def run_timer():
        if engine.event_loop.run_timer(timer_id):
          flush_written_html(force=True)

      try:
        self.root.after(max(int(delay), 0), run_timer)
      except tk.TclError:
        pass

    engine.event_loop.set_timer_scheduler(schedule_timer)

    globals_dict = {
        "window": window,
        "document": document,
        "location": window.location,
        "console": console,
        "alert": lambda *args: None,
    }
    for source in sources:
      try:
        engine.execute(source, globals_dict)
      except Exception as exc:
        parser.js_errors.append(str(exc))

    document.readyState = "interactive"
    document.dispatchEvent(JSEvent("DOMContentLoaded"))
    document.readyState = "complete"
    window.dispatchEvent(JSEvent("load"))
    engine.event_loop.run_microtasks()
    flush_written_html()
    rendered[0] = True

  def _search_query(self, page_url):
    from urllib.parse import parse_qs, urlsplit

    return parse_qs(urlsplit(page_url).query).get("q", [""])[0]

  def _submit_form(
      self, form_id, action_url="", method="", submitter_name="", submitter_value=""
  ):
    if form_id is None:
      return
    form = self.page_forms.get(form_id, {})
    target_url = action_url or form.get("action", "") or self.url_entry.get()
    resolved_url = self._resolve_url(self.url_entry.get(), target_url)
    request_method = (method or form.get("method", "get")).upper()
    if request_method not in ("GET", "POST"):
      request_method = "GET"

    fields = list(form.get("hidden_fields", []))
    for field in self.form_fields:
      if field.get("form_id") != form_id or not field.get("name"):
        continue
      widget = field["widget"]
      value = (
          widget.get("1.0", "end-1c")
          if field.get("multiline")
          else widget.get()
      )
      if value == field.get("placeholder"):
        value = ""
      fields.append((field["name"], value))
    if submitter_name:
      fields.append((submitter_name, submitter_value))

    try:
      response = self.session.request(
          request_method,
          resolved_url,
          params=fields if request_method == "GET" else None,
          data=fields if request_method == "POST" else None,
          timeout=10,
          allow_redirects=True,
      )
      response.raise_for_status()
      final_url = response.url or resolved_url
      self._set_address_text(final_url)
      self._update_active_tab(final_url)
      self.render_html(response.text, final_url)
    except Exception as exc:
      messagebox.showerror("Error", f"Не удалось отправить форму на сайт:\n{exc}")

  def _submit_search(self, query, page_url):
    from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

    parts = urlsplit(page_url)
    params = parse_qs(parts.query)
    params["q"] = [query]
    search_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params, doseq=True), ""))
    self._set_address_text(search_url)
    self.load_page()

  def _submit_unbound_search(self, query):
    query = query.strip()
    if not query:
      return
    self._set_address_text(query)
    self.load_page()

  def _search_api_url(self, query):
    from urllib.parse import quote_plus
    # Наш поисковик на 1000+ сайтов
    return "https://visearch.pfeh-qqq.workers.dev/?q=" + quote_plus(query.strip())

  def _search_result_items(self, data):
    if isinstance(data, list):
      return data
    if isinstance(data, dict):
      for key in ("results", "items", "data", "result", "web_results"):
        value = data.get(key)
        if isinstance(value, list):
          return value
        if isinstance(value, dict):
          nested = self._search_result_items(value)
          return nested if nested else list(value.values())
      return [data]
    return []

  def _render_search_response(self, response, query):
    body = (getattr(response, "text", "") or "").strip()
    if "NOT_FOUND || NETWORK_CASCADE" in body.splitlines():
      return True

    try:
      data = response.json()
    except (ValueError, AttributeError):
      data = None

    elements = [{"tag": "h1", "text": "Результаты поиска: " + query, "font": "Arial"}]
    if data is None:
      for line in body.splitlines():
        if "||" in line:
          title, result_url = [part.strip() for part in line.split("||", 1)]
          if title and result_url:
            elements.append({
                "tag": "a", "text": title, "href": result_url,
                "action_url": result_url, "method": "get", "font": "Arial",
            })
        elif line.strip():
          elements.append({"tag": "p", "text": line.strip(), "font": "Arial"})
      if len(elements) == 1:
        elements.append({"tag": "p", "text": "Ничего не найдено.", "font": "Arial"})
    else:
      items = self._search_result_items(data)
      if not items:
        elements.append({"tag": "p", "text": "Ничего не найдено.", "font": "Arial"})
      for item in items[:30]:
        if isinstance(item, dict):
          title = next((item[key] for key in ("title", "name", "heading") if item.get(key)), "")
          url = next((item[key] for key in ("url", "link", "href") if item.get(key)), "")
          description = next(
              (item[key] for key in ("description", "snippet", "summary", "text", "content") if item.get(key)),
              "",
          )
        else:
          title, url, description = str(item), "", ""
        title = str(title or url or "Результат")
        if url:
          elements.append({
              "tag": "a", "text": title, "href": str(url),
              "action_url": str(url), "method": "get", "font": "Arial",
          })
        else:
          elements.append({"tag": "p", "text": title, "font": "Arial"})
        if description:
          elements.append({"tag": "p", "text": str(description), "font": "Arial"})

    parser = SimpleHTMLParser()
    parser.elements = elements
    self.render_generic_page(parser)
    return False

  def _load_search_cascade(self, query):
    from urllib.parse import urlencode
    # Мама птица (DuckDuckGo), чтобы найти больше результатов, если наш поисковик не дал полного ответа
    search_url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    try:
      response = self.session.get(search_url, timeout=10)
      response.raise_for_status()
      final_url = response.url or search_url
      self._set_address_text(final_url)
      self._update_active_tab(final_url)
      self.render_html(response.text, final_url)
    except Exception as exc:
      print(f"DuckDuckGo запретили нам вход на данную страницу: {exc}")
      # Генерируем простую HTML-страничку с ошибкой без вызова кривых методов!
      error_html = f"""
      <html>
        <body style="font-family: Arial; padding: 20px;">
          <h2>⚠️ Ошибка загрузки</h2>
          <p>Не удалось получить результаты поиска:</p>
          <code style="color: red;">{exc}</code>
        </body>
      </html>
      """
      self.render_html(error_html, search_url)

  def _handle_field_enter(self, widget, form_id, input_type, field_name):
    if form_id is not None:
      self._submit_form(form_id)
      return "break"
    if input_type == "search" or field_name.lower() in ("q", "query", "search"):
      self._submit_unbound_search(widget.get())
      return "break"

  def load_page(self):
    url = self.url_entry.get().strip()
    
    # 🌟 ВОТ ТУТ МАГИЯ: если пусто или плейсхолдер — открываем локальный мост!
    if not url or url == self.url_placeholder:
      url = self.bridge_server.url

    search_query = None
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
      host = url.split("/", 1)[0]
      is_domain = "." in host or host.lower().startswith("localhost")
      if is_domain and not re.search(r"\s", url):
        url = "https://" + url
      else:
        search_query = url
        url = self._search_api_url(search_query)

    # 🌟 Если мы на стартовой странице — возвращаем красивый плейсхолдер!
    if url == self.bridge_server.url:
      self._restore_url_placeholder()
    else:
      self._set_address_text(url)

    self._update_active_tab(url)

    if search_query is None:
      cached_html = self.cache.get_page(url)
      if cached_html:
        print("⚡️ Загружено из локального кэша!")
        self.render_html(cached_html, url)
        return

    try:
      # Пробуем обычный запрос
      response = self.session.get(url, timeout=10)
      
      # Если сайт выдаёт 403 или 503 — подключаем VIPROXY для обхода блокировок
      if response.status_code in (403, 503):
        print(f"🛑 Ошибка {response.status_code}! Врубаем VIPROXY...")
        proxy_url = f"https://viproxy.pfeh-qqq.workers.dev/?url={quote_plus(url)}"
        response = self.session.get(proxy_url, timeout=10)

      response.raise_for_status()

      if search_query is not None:
        if self._render_search_response(response, search_query):
          self._load_search_cascade(search_query)
      else:
        # печеньки 🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪🍪
        self.cache.set_page(url, response.text)
        if response.cookies:
          self.cache.save_cookies(urlsplit(url).netloc, response.cookies.get_dict())
        self.render_html(response.text, url)

    except Exception as e:
      # 💥 Если даже прямая сеть упала, добиваем через твой прокси!
      try:
        print(f"⚠️ Сетевой сбой ({e})! Пробуем спасти через VIPROXY...")
        proxy_url = f"https://viproxy.pfeh-qqq.workers.dev/?url={quote_plus(url)}"
        response = self.session.get(proxy_url, timeout=10)
        response.raise_for_status()
        self.render_html(response.text, url)
      except Exception as proxy_e:
        print(f"😭 Прокси тоже не пробился: {proxy_e}")
        self._load_search_cascade(search_query if search_query else url)

  def on_canvas_click(self, event):
    real_y = self.canvas.canvasy(event.y)
    for link in self.links:
      if (
          link["x1"] <= event.x <= link["x2"]
          and link["y1"] <= real_y <= link["y2"]  # Используем real_y вместо event.y!
      ):
        # ... остальной код метода без изменений ...
        clicked_text = link["text"]
        target_href = link.get("href") or link.get("action_url", "")
        tag = link.get("tag", "a")
        dom_element = (
          self.page_document.getElementById(link.get("element_id"))
          if self.page_document and link.get("element_id")
          else None
        )
        had_click_handler = bool(
          dom_element and dom_element.listeners.get("click")
        )
        if dom_element:
          dom_event = JSEvent("click", {"bubbles": True, "cancelable": True})
          dom_element.dispatchEvent(dom_event)
          if dom_event.defaultPrevented:
            self._refresh_dom_page()
            return

        if tag == "button":
          if link.get("submit") and link.get("form_id") is not None:
            self._submit_form(
                link["form_id"],
                link.get("action_url", ""),
                link.get("method", "get"),
                link.get("name", ""),
                link.get("value", ""),
            )
            return
          if not target_href:
            if had_click_handler:
              self._refresh_dom_page()
              return
            messagebox.showinfo("Button", f"Нажата кнопка: {clicked_text}")
            return

          resolved_url = self._resolve_url(self.url_entry.get(), target_href)
          method = (link.get("method") or "get").upper()

          try:
            response = self.session.request(method, resolved_url, timeout=10, allow_redirects=True)
            response.raise_for_status()
            self._set_address_text(resolved_url)
            self._update_active_tab(resolved_url)
            self.render_html(response.text, resolved_url)
          except Exception as exc:
            messagebox.showerror("Error", f"Не удалось отправить запрос на сайт:\n{exc}")
          return

        if target_href:
          resolved_url = self._resolve_url(self.url_entry.get(), target_href)
          self._set_address_text(resolved_url)
          self.load_page()
          return

        messagebox.showinfo(
            "Button", f"Кликнули по интерактивному элементу: {clicked_text}"
        )
        return

  def _refresh_dom_page(self):
    if not isinstance(self.page_document, Document):
      return
    parser = SimpleHTMLParser()
    parser.feed(self.page_document.to_html())
    parser.dom_document = self.page_document
    parser.external_style_text = self.page_external_style_text
    parser.style_text += parser.external_style_text
    parser.bg_color = css_engine.detect_background_from_css(parser.style_text, default_bg="white")
    css_engine.apply_css_styles(parser)
    self.render_generic_page(parser)

  def clear_all_cache(self):
    if self.cache.clear_cache():
      messagebox.showinfo("cache", "All cache in browser was cleared. | Весь кэш в браузере был успешно очищен")


if __name__ == "__main__":
  root = tk.Tk()
  app = SimpleBrowser(root)
  root.mainloop()
