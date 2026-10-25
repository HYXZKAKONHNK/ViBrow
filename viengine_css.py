import re
import tkinter as tk

class CSSEngine:
  def __init__(self, style_text=""):
    self.style_text = style_text
    self.css_vars = {}
    self.style_rules = []

  def process_image_and_search_styles(self, element, computed_styles):
        tag = element.get("tag", "").lower()
        
        if tag == "img":
            # Авто-ограничение максимальной ширины, чтобы картинки не вылезали за экран!
            element["max_width"] = computed_styles.get("max-width", "100%")
            element["object_fit"] = computed_styles.get("object-fit", "cover")
            
            # Парсим ширину и высоту, если они заданы в CSS
            width_val = computed_styles.get("width", "")
            height_val = computed_styles.get("height", "")
            
            if width_val and width_val != "auto":
                element["css_width"] = width_val
            if height_val and height_val != "auto":
                element["css_height"] = height_val
                
            # Округление углов у картинок (border-radius)
            if computed_styles.get("border-radius"):
                element["border_radius"] = computed_styles.get("border-radius")

        classes = element.get("classes", [])
        is_search_card = any(cls in ("result", "g", "b_algo", "card", "product-card") for cls in classes)
        
        if is_search_card or tag in ("article", "section"):
            element["is_card"] = True
            # Задаем красивую тень и отступы для карточек поиска
            element["margin_bottom"] = computed_styles.get("margin-bottom", "12px")
            element["padding"] = computed_styles.get("padding", "10px")
            if not element.get("bg_color"):
                element["bg_color"] = self.resolve_css_color(computed_styles.get("background", ""), "#ffffff")

  def parse_css_vars(self):
    css = self.style_text or ""
    matches = re.findall(r"--([a-zA-Z0-9_-]+)\s*:\s*([^;}]+)", css)
    self.css_vars = {}
    for name, value in matches:
      self.css_vars[name.strip()] = value.strip().replace("!important", "")

  def resolve_css_color(self, value, fallback="white"):
    if not value:
      return fallback

    value = value.strip().replace("!important", "")
    if not value:
      return fallback

    # 1. Распаковываем var(--name, fallback_color)
    match_var = re.search(r"var\(\s*--([a-zA-Z0-9_-]+)(?:\s*,\s*([^)]+))?\)", value, flags=re.IGNORECASE)
    if match_var:
      var_name = match_var.group(1)
      var_fallback = match_var.group(2) or fallback
      if var_name in self.css_vars:
        return self.resolve_css_color(self.css_vars[var_name], var_fallback)
      return self.resolve_css_color(var_fallback, fallback)

    # 2. 🔥 ГОЛЫЕ ПЕРЕМЕННЫЕ (например: color_var1, --btn-bg, my-color) 🔥
    clean_name = value.lstrip("-").strip()
    if clean_name in self.css_vars:
      return self.resolve_css_color(self.css_vars[clean_name], fallback)

    # Если внутри строки спрятана переменная без var(), вытаскиваем её!
    for v_name, v_val in self.css_vars.items():
      if v_name in value:
        return self.resolve_css_color(v_val, fallback)

    if value.lower() == "transparent":
      return fallback

    # 3. Обработка HEX-цветов (#fff, #ffffff, #ffffff80)
    hex_match = re.search(r"#(?:[0-9a-fA-F]{3,4}){1,2}", value)
    if hex_match:
      hex_value = hex_match.group(0)
      if len(hex_value) in (4, 5):
        hex_value = "#" + "".join(ch * 2 for ch in hex_value[1:])
      if len(hex_value) == 9:
        hex_value = hex_value[:7]
      return hex_value

    # 4. Обработка rgb() и rgba()
    rgb_match = re.search(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)",
        value,
        flags=re.IGNORECASE,
    )
    if rgb_match:
      r, g, b = [int(float(part)) for part in rgb_match.groups()[:3]]
      return "#{:02x}{:02x}{:02x}".format(r, g, b)

    # 5. Именованные цвета (red, blue, darkgray и т.д.)
    if re.fullmatch(r"[a-zA-Z]+", value):
      return value.lower()

    return fallback

  def parse_css_declarations(self, declarations_text):
      """
      Пуленепробиваемый парсер свойств (color, bg, margin)! 🛡️✨
      Никогда не валит движок, даже если в CSS лютый мусор!
      """
      declarations = {}
      if not declarations_text:
        return declarations

      # Разбиваем по точке с запятой, защищаясь от косяков верстки
      raw_pairs = declarations_text.split(";")
      for pair in raw_pairs:
        if ":" not in pair:
          continue
        try:
          prop, val = pair.split(":", 1)
          prop = prop.strip().lower()
          val = val.strip()
          if prop and val:
            declarations[prop] = val
        except Exception as e:
          # Если отдельное правило кривое — просто пропускаем его и идем дальше!
          continue

      return declarations

  def parse_css_value(self, style, *keys):
    """ Поиск конкретного ключа в строке стилей """
    if not style:
      return ""
    for part in style.split(";"):
      if ":" not in part:
        continue
      key, value = [p.strip().lower() for p in part.split(":", 1)]
      if key in keys:
        return value.strip()
    return ""

  def selector_matches(self, selector, element):
    """ Проверка совпадения CSS-селектора с элементом """
    selector = re.sub(r"::?[\w-]+(?:\([^)]*\))?", "", selector).strip()
    selector_parts = selector.split()
    if not selector_parts:
      return False
    selector = selector_parts[-1]
    attributes = re.findall(r"\[\s*([\w-]+)\s*=\s*([^\]]+)\]", selector)
    for name, value in attributes:
      value = value.strip().strip("'\"")
      if name.lower() == "type" and element.get("input_type", "").lower() != value.lower():
        return False
    selector = re.sub(r"\[[^\]]+\]", "", selector)
    tag_match = re.match(r"^[a-zA-Z][\w-]*", selector)
    element_tag = element.get("selector_tag", element.get("tag", "")).lower()
    if tag_match and tag_match.group(0).lower() != element_tag:
      return False
    id_match = re.search(r"#([\w-]+)", selector)
    if id_match and id_match.group(1) != element.get("id", ""):
      return False
    classes = set(re.findall(r"\.([\w-]+)", selector))
    return classes.issubset(set(element.get("classes", [])))

  def apply_css_styles(self, elements):
    """
    Применяет CSS-правила, раскрашивает кнопки, картинки, карточки поиска и сетки! 🎨💥
    Защищено от вылетов на сложных сайтах! 🛡️
    """
    # 🌟 Используем очистку CSS от сложных блоков @media/@keyframes (если метод есть) или чистим комментарии
    if hasattr(self, "sanitize_and_parse_css"):
      css = self.sanitize_and_parse_css(self.style_text or "")
    else:
      css = re.sub(r"/\*.*?\*/", "", self.style_text or "", flags=re.DOTALL)

    self.parse_css_vars()
    self.style_rules = []
    
    # 🛡️ Оборачиваем сбор правил в try...except
    try:
      for selector_group, declarations_text in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        declarations = self.parse_css_declarations(declarations_text)
        for selector in selector_group.split(","):
          selector = selector.strip()
          if selector:
            self.style_rules.append((selector, declarations))
    except Exception as exc:
      print(f"⚠️ Ошибка при парсинге правил CSS: {exc}")

    # 🚀 Применяем стили к каждому элементу
    for element in elements:
      try:
        computed = {}
        for selector, declarations in self.style_rules:
          if self.selector_matches(selector, element):
            computed.update(declarations)
        computed.update(self.parse_css_declarations(element.get("style", "")))

        # 🎨 Разбираем цвет фона (с поиском в переменных!)
        background = computed.get("background-color") or computed.get("background", "")
        if background:
          element["bg_color"] = self.resolve_css_color(background, "white")

        # ✏️ Разбираем цвет текста
        if computed.get("color"):
          element["fg_color"] = self.resolve_css_color(computed["color"], "black")

        # 🖼️ Разбираем рамки (border)
        border_color = computed.get("border-color", "")
        if not border_color and computed.get("border"):
          border_color = computed["border"]
        if border_color:
          element["border_color"] = self.resolve_css_color(border_color, "#cccccc")

        if computed.get("border-radius"):
          element["border_radius"] = computed["border-radius"]

        # ⚡️ ПОДДЕРЖКА FLEX / GRID СЕТОК (для галерей картинок и каталогов)
        display_val = computed.get("display", "").lower()
        if display_val in ("flex", "grid", "inline-flex", "inline-grid"):
          element["is_container"] = True
          element["display_type"] = display_val
          element["flex_direction"] = computed.get("flex-direction", "row")
          element["gap"] = computed.get("gap", "8px")

        # 📸 Вызываем обработчик картинок и поисковой выдачи!
        if hasattr(self, "process_image_and_search_styles"):
          self.process_image_and_search_styles(element, computed)

      except Exception as elem_exc:
        # 🛡️ Если ОДИН элемент кривой — прогоняем его и рендерим остальные без вылета!
        continue

  def detect_background_from_css(self, *args, **kwargs):
    """ Автоматический поиск фона страницы из body / html (Защищено от лишних аргументов!) 🚀 """
    default_bg = kwargs.get("default_bg")
    if not default_bg and args:
      default_bg = args[0]
    if not default_bg:
      default_bg = "white"

    css = self.style_text or ""
    self.parse_css_vars()
    patterns = [
        r"body\s*\{[^}]*background(?:-color)?\s*:\s*([^;{}]+)",
        r"html\s*\{[^}]*background(?:-color)?\s*:\s*([^;{}]+)",
    ]
    for pattern in patterns:
      try:
        match = re.search(pattern, css, flags=re.IGNORECASE | re.DOTALL)
        if match:
          value = match.group(1).strip().replace("!important", "")
          value = value.split()[0]
          resolved = self.resolve_css_color(value, default_bg)
          if resolved:
            return resolved
      except Exception:
        continue
    return default_bg

  def sanitize_and_parse_css(self, css_text):
      """
      УЛЬТРА-ОЧИСТКА И ЗАЩИТА ОТ СЛОЖНОГО CSS! 💣🛡️
      Убирает @media, @keyframes, @supports и мягко резолвит calc()/clamp()!
      """
      if not css_text:
        return ""

      # 1. Вырезаем комментарии /* ... */
      css = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)

      # 2. Очищаем от тяжелых директив @keyframes, @font-face, @import, @supports
      css = re.sub(
          r"@(keyframes|font-face|import|supports)[^{}]*\{[^{}]*\}",
          "",
          css,
          flags=re.IGNORECASE | re.DOTALL,
      )

      # 3. Раскрываем @media блоки, доставая из них полезные правила!
      # Заменяем @media ... { rules } на просто rules
      css = re.sub(
          r"@media[^{}]*\{([\s\S]*?)\}\s*\}",
          r"\1",
          css,
          flags=re.IGNORECASE,
      )

      # 4. Превращаем calc(100% - 20px) или clamp(...) в безопасные фоллбэки!
      css = re.sub(
          r"calc\([^)]+\)", "auto", css, flags=re.IGNORECASE
      )  # Если там calc, ставим auto
      css = re.sub(
          r"clamp\([^)]+\)", "auto", css, flags=re.IGNORECASE
      )  # Если clamp, ставим auto

      return css

  
