"""gif_render — рендер GIF-анимаций и видеокадров для Tkinter-канваса ViBrow.

Без сторонних GUI-библиотек: только PIL (Pillow) + tkinter.
Классы:
  - CustomHeaderRenderer: анимированная гифка в шапке браузера (32x32).
  - GIFRender: анимированная картинка <img src="*.gif"> прямо на канвасе страницы.
  - VideoFramePlayer: покадровый рендер видео (mp4/webm), если доступен ffmpeg,
    иначе показывается poster-кадр/заглушка с кнопкой «Открыть видео».
Все классы имеют интерфейс start() / stop(), чтобы движок мог единовременно
останавливать все анимации при перерисовке страницы.
"""

import os
import shutil
import subprocess
import tempfile
import time

from PIL import Image, ImageSequence, ImageTk


def _load_gif_frames(gif_path_or_bytes, max_size=(640, 480)):
    """Возвращает список (PhotoImage, delay_сек) по файлу/bytes GIF."""
    image = Image.open(gif_path_or_bytes)
    frames = []
    for frame in ImageSequence.Iterator(image):
        rgba = frame.convert("RGBA")
        if max_size and (rgba.width > max_size[0] or rgba.height > max_size[1]):
            rgba.thumbnail(max_size, Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
        delay_ms = frame.info.get("duration", 100) or 100
        frames.append((ImageTk.PhotoImage(rgba), max(delay_ms, 20) / 1000.0))
    return frames


class CustomHeaderRenderer:
    """Прокручивает Vibrow_anim.gif внутри маленького canvas в шапке окна."""

    def __init__(self, canvas, gif_path, size=32):
        self.canvas = canvas
        self.gif_path = str(gif_path)
        self.size = size
        self.frames = []
        self.current_frame_index = 0
        self._running = False
        self._after_id = None
        try:
            for photo, _delay in _load_gif_frames(self.gif_path, max_size=(size, size)):
                self.frames.append(photo)
        except Exception:
            self.frames = []

    def get_current_gif_frame(self):
        """Возвращает текущий кадр гифки и переключает на следующий! ⚡️"""
        if not self.frames:
            return None
        frame = self.frames[self.current_frame_index]
        self.current_frame_index = (self.current_frame_index + 1) % len(self.frames)
        return frame

    def _tick(self):
        if not self._running:
            return
        frame = self.get_current_gif_frame()
        if frame is not None:
            self.canvas.delete("gif-frame")
            self.canvas.create_image(
                self.size // 2, self.size // 2, anchor="center",
                image=frame, tags="gif-frame",
            )
        self._after_id = self.canvas.after(90, self._tick)

    def start(self):
        if self._running or not self.frames:
            return
        self._running = True
        self._tick()

    def stop(self):
        self._running = False
        try:
            if self._after_id is not None:
                self.canvas.after_cancel(self._after_id)
        except Exception:
            pass
        self._after_id = None


class GIFRender:
    """Анимация <img src=".gif"> на канвасе страницы по координатам x, y."""

    def __init__(self, canvas, source, x=0, y=0, session=None, max_size=(560, 420)):
        self.canvas = canvas
        self.source = source
        self.x = x
        self.y = y
        self.session = session
        self.max_size = max_size
        self.frames = []
        self.index = 0
        self._running = False
        self._after_id = None
        self.image_item = None

    def _open_source(self):
        if isinstance(self.source, (bytes, bytearray)) or hasattr(self.source, "read"):
            return Image.open(self.source)
        path = str(self.source)
        if os.path.exists(path):
            return Image.open(path)
        if path.startswith("http") and self.session is not None:
            response = self.session.get(path, timeout=10)
            response.raise_for_status()
            from io import BytesIO
            return Image.open(BytesIO(response.content))
        raise FileNotFoundError(path)

    def _decode(self):
        image = self._open_source()
        frames = []
        for frame in ImageSequence.Iterator(image):
            rgba = frame.convert("RGBA")
            if rgba.width > self.max_size[0] or rgba.height > self.max_size[1]:
                rgba.thumbnail(self.max_size, Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
            delay_ms = frame.info.get("duration", 100) or 100
            frames.append((ImageTk.PhotoImage(rgba), max(delay_ms, 20) / 1000.0))
        return frames

    def start(self):
        try:
            self.frames = self._decode()
        except Exception:
            self.frames = []
        if not self.frames:
            return
        self._running = True
        self._show_current()

    def _show_current(self):
        if not self._running:
            return
        photo, delay = self.frames[self.index]
        self.index = (self.index + 1) % len(self.frames)
        if self.image_item is None:
            self.image_item = self.canvas.create_image(self.x, self.y, anchor="nw", image=photo)
        else:
            self.canvas.itemconfigure(self.image_item, image=photo)
        self._after_id = self.canvas.after(int(delay * 1000), self._show_current)

    @property
    def width(self):
        if self.frames:
            return self.frames[0][0].width()
        return 0

    @property
    def height(self):
        if self.frames:
            return self.frames[0][0].height()
        return 0

    def stop(self):
        self._running = False
        try:
            if self._after_id is not None:
                self.canvas.after_cancel(self._after_id)
        except Exception:
            pass
        self._after_id = None


class VideoFramePlayer:
    """Показывает кадры видео на канвасе через ffmpeg (если он в системе).

    Если ffmpeg недоступен — рисуется poster-изображение (или заглушка) и
    кнопка-плей, по клику на которую видео открывается системным плеером.
    """

    def __init__(self, canvas, video_url, x=0, y=0, width=320, height=180,
                 poster_url=None, session=None):
        self.canvas = canvas
        self.video_url = video_url
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.poster_url = poster_url
        self.session = session
        self.frames = []
        self.index = 0
        self.playing = False
        self._running = False
        self._after_id = None
        self.image_item = None
        self.button_items = []
        self.click_box = None
        self._tmpdir = None

    # --- загрузка -----------------------------------------------------
    def _download_video(self):
        path = str(self.video_url)
        if os.path.exists(path):
            return path
        if path.startswith("http") and self.session is not None:
            response = self.session.get(path, timeout=15)
            response.raise_for_status()
            self._tmpdir = tempfile.mkdtemp(prefix="vibrow_video_")
            out = os.path.join(self._tmpdir, os.path.basename(path.split("?")[0]) or "video.mp4")
            with open(out, "wb") as handle:
                handle.write(response.content)
            return out
        raise FileNotFoundError(path)

    def _extract_frames(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return []
        video_path = self._download_video()
        self._tmpdir = self._tmpdir or tempfile.mkdtemp(prefix="vibrow_video_")
        frames_dir = os.path.join(self._tmpdir, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", video_path,
             "-vf", f"fps=8,scale={self.width}:-1", "-frames:v", "96",
             os.path.join(frames_dir, "f%04d.png")],
            timeout=30, check=False,
        )
        photos = []
        for name in sorted(os.listdir(frames_dir)):
            if name.endswith(".png"):
                photos.append((ImageTk.PhotoImage(Image.open(os.path.join(frames_dir, name)).convert("RGBA")), 0.125))
        return photos

    def _load_poster(self):
        if not self.poster_url:
            return None
        try:
            from io import BytesIO
            if self.poster_url.startswith("http") and self.session is not None:
                response = self.session.get(self.poster_url, timeout=10)
                image = Image.open(BytesIO(response.content)).convert("RGBA")
            else:
                image = Image.open(self.poster_url).convert("RGBA")
            if image.width > self.width or image.height > self.height:
                image.thumbnail((self.width, self.height), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    # --- отрисовка ----------------------------------------------------
    def start(self):
        try:
            self.frames = self._extract_frames()
        except Exception:
            self.frames = []
        self._running = True
        if self.frames:
            self._draw_frame()
            self._draw_play_toggle()
            self.playing = True
            self._schedule_next()
        else:
            self._draw_placeholder()

    def _ensure_image_item(self):
        if self.image_item is None:
            self.image_item = self.canvas.create_rectangle(
                self.x, self.y, self.x + self.width, self.y + self.height,
                fill="#000000", outline="#333333",
            )
            self.image_item = self.canvas.create_image(self.x, self.y, anchor="nw")
        return self.image_item

    def _draw_frame(self):
        photo, _delay = self.frames[self.index]
        item = self._ensure_image_item()
        self.canvas.delete(item)
        self.image_item = self.canvas.create_image(self.x, self.y, anchor="nw", image=photo)

    def _schedule_next(self):
        if not (self._running and self.playing and self.frames):
            return
        _photo, delay = self.frames[self.index]
        self.index = (self.index + 1) % len(self.frames)
        self._after_id = self.canvas.after(int(delay * 1000), self._play_tick)

    def _play_tick(self):
        if not (self._running and self.playing):
            return
        self._draw_frame()
        self._schedule_next()

    def toggle_playback(self):
        self.playing = not self.playing
        self._clear_button()
        self._draw_play_toggle()
        if self.playing:
            self._schedule_next()

    def _clear_button(self):
        for item in self.button_items:
            self.canvas.delete(item)
        self.button_items = []

    def _draw_play_toggle(self):
        cx = self.x + self.width - 18
        cy = self.y + self.height - 18
        self.button_items.append(self.canvas.create_oval(cx - 12, cy - 12, cx + 12, cy + 12, fill="#111111", outline="#ffffff"))
        label = "❚❚" if self.playing else "▶"
        self.button_items.append(self.canvas.create_text(cx, cy, text=label, fill="#ffffff", font=("Arial", 9, "bold")))
        self.click_box = (cx - 14, cy - 14, cx + 14, cy + 14)

    def _draw_placeholder(self):
        poster = self._load_poster()
        if poster is not None:
            self.canvas.create_image(self.x, self.y, anchor="nw", image=poster)
            self.frames = [(poster, 1.0)]
        else:
            self.canvas.create_rectangle(self.x, self.y, self.x + self.width, self.y + self.height, fill="#1c1c1e", outline="#444444")
            self.canvas.create_text(self.x + self.width // 2, self.y + self.height // 2 - 12, text="🎬 Видео", fill="#ffffff", font=("Arial", 12, "bold"))
        self._draw_play_toggle()

    def handle_click(self, event):
        """True, если клик пришёлся на кнопку play/pause."""
        box = self.click_box
        if box and box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]:
            if self.frames:
                self.toggle_playback()
            else:
                try:
                    import webbrowser
                    webbrowser.open(self.video_url)
                except Exception:
                    pass
            return True
        return False

    def stop(self):
        self._running = False
        self.playing = False
        try:
            if self._after_id is not None:
                self.canvas.after_cancel(self._after_id)
        except Exception:
            pass
        self._after_id = None
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
