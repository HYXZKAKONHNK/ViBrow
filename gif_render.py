import time
import canvas


class CustomHeaderRenderer:

  def __init__(self, gif_frames=None):
    self.canvas = canvas
    self.gif_path = gif_path
    self.gif_frames = gif_frames or []  # Список кадров твоей ViBrow_anim.gif
    self.current_frame_index = 0
    self.last_frame_time = time.time()
    self.frame_delay = 0.08  # Скорость анимации (в секундах)

  def get_current_gif_frame(self):
    """Возвращает текущий кадр гифки и переключает на следующий! ⚡️"""
    if not self.gif_frames:
      return None

    now = time.time()
    if now - self.last_frame_time >= self.frame_delay:
      self.current_frame_index = (self.current_frame_index + 1) % len(
          self.gif_frames
      )
      self.last_frame_time = now

    return self.gif_frames[self.current_frame_index]

  def render_custom_titlebar(self, canvas, window_width, titlebar_height=35):
      """
      Собственный рендер шапки без сторонних GUI библиотек! 🎨💥
      """
      # 1. Рисуем фон шапки (серый/светлый)
      canvas.draw_rect(
          x=0,
          y=0,
          width=window_width,
          height=titlebar_height,
          color="#F0F0F0",
      )

      # 2. Рисуем иконку и заголовок СЛЕВА 👈
      canvas.draw_image(
          x=10, y=7, width=20, height=20, image_path="resourses/ViBrow_logo.png"
      )
      canvas.draw_text(
          x=38,
          y=22,
          text="Vibrow",
          font_size=13,
          color="#333333",
          font_weight="bold",
      )

      # 3. Рисуем АНИМИРОВАННУЮ ГИФКУ РОВНО ПО ЦЕНТРУ! 🎯🔥
      current_frame = self.get_current_gif_frame()
      gif_w, gif_h = 24, 24
      center_x = (window_width - gif_w) // 2  # Считаем точный центр!
      center_y = (titlebar_height - gif_h) // 2

      if current_frame:
        canvas.draw_image_frame(
            x=center_x, y=center_y, width=gif_w, height=gif_h, frame=current_frame
        )

      # 4. Рисуем кнопки управления (Минимизировать, Закрыть) СПРАВА 👉
      canvas.draw_text(
          x=window_width - 30,
          y=22,
          text="✕",
          font_size=14,
          color="#555555",
      )
      canvas.draw_text(
          x=window_width - 55,
          y=22,
          text="🗖",
          font_size=12,
          color="#555555",
      )
      canvas.draw_text(
          x=window_width - 80,
          y=22,
          text="—",
          font_size=14,
          color="#555555",
      )