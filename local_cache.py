import os
import hashlib
import json
import time
import shutil

class LocalCache:
    def __init__(self, cache_dir="cache"):
        # Определяем путь к папке cache рядом со скриптом
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cache_path = os.path.join(base_dir, cache_dir)
        
        # Автоматически создаем папку, если ее нет! 🔥
        self._ensure_cache_dir()

        # Пути к специальным файлам хранения 📁
        self.cookies_file = os.path.join(self.cache_path, "cookies.json")
        self.logins_file = os.path.join(self.cache_path, "logins.json")
        self.vars_file = os.path.join(self.cache_path, "variables.json")

    def _ensure_cache_dir(self):
        """Проверяет существование директории кэша"""
        if not os.path.exists(self.cache_path):
            os.makedirs(self.cache_path)

    def _get_filename(self, key: str, prefix="page_", ext=".json") -> str:
        """Хэширует URL в MD5 для безопасного названия файла"""
        hashed_key = hashlib.md5(key.encode('utf-8')).hexdigest()
        return os.path.join(self.cache_path, f"{prefix}{hashed_key}{ext}")

    # ==================== 1. КЭШ СТРАНИЦ (HTML) ====================
    def set_page(self, url: str, html_content: str):
        """Сохраняет HTML-код страницы"""
        filename = self._get_filename(url, prefix="page_", ext=".json")
        cache_data = {"timestamp": time.time(), "html": html_content}
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[Cache Error] Ошибка сохранения страницы: {e}")

    def get_page(self, url: str, max_age_seconds: int = 86400):
        """Достает HTML страницы из кэша"""
        filename = self._get_filename(url, prefix="page_", ext=".json")
        if not os.path.exists(filename):
            return None
        try:
            with open(filename, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            if time.time() - cache_data.get("timestamp", 0) > max_age_seconds:
                return None
            return cache_data.get("html")
        except Exception:
            return None

    # ==================== 2. КЭШ ВИДЕО И МЕДИАФАЙЛОВ ====================
    def save_video(self, url: str, video_bytes: bytes, ext=".mp4") -> str:
        """Сохраняет бинарные данные видео в файл и возвращает путь к нему"""
        filename = self._get_filename(url, prefix="video_", ext=ext)
        try:
            with open(filename, "wb") as f:
                f.write(video_bytes)
            print(f"[Cache] Видео успешно сохранено: {filename}")
            return filename
        except Exception as e:
            print(f"[Cache Error] Ошибка сохранения видео: {e}")
            return ""

    def get_video_path(self, url: str, ext=".mp4") -> str:
        """Возвращает путь к видео из кэша, если файл существует"""
        filename = self._get_filename(url, prefix="video_", ext=ext)
        if os.path.exists(filename):
            return filename
        return ""

    # ==================== 3. КУКИ (COOKIES) ====================
    def save_cookies(self, domain: str, cookies_dict: dict):
        """Сохраняет куки для конкретного сайта"""
        data = self._load_json(self.cookies_file)
        data[domain] = cookies_dict
        self._save_json(self.cookies_file, data)

    def get_cookies(self, domain: str) -> dict:
        """Возвращает куки для сайта"""
        data = self._load_json(self.cookies_file)
        return data.get(domain, {})

    # ==================== 4. ЛОГИНЫ И ПАРОЛИ ====================
    def save_login(self, domain: str, username: str, password_hash: str):
        """Сохраняет логин и пароль для сайта"""
        data = self._load_json(self.logins_file)
        data[domain] = {"username": username, "password": password_hash}
        self._save_json(self.logins_file, data)

    def get_login(self, domain: str) -> dict:
        """Достает логин и пароль для сайта"""
        data = self._load_json(self.logins_file)
        return data.get(domain, None)

    # ==================== 5. ПЕРЕМЕННЫЕ ====================
    def set_var(self, key: str, value):
        """Сохраняет любую переменную браузера"""
        data = self._load_json(self.vars_file)
        data[key] = value
        self._save_json(self.vars_file, data)

    def get_var(self, key: str, default=None):
        """Достает переменную"""
        data = self._load_json(self.vars_file)
        return data.get(key, default)

    # ==================== 6. ПОЛНЫЙ СБРОС КЭША ====================
    def clear_cache(self):
        """Удаляет абсолютно всё содержимого папки cache 💣"""
        try:
            if os.path.exists(self.cache_path):
                for filename in os.listdir(self.cache_path):
                    file_path = os.path.join(self.cache_path, filename)
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
            print("[Cache] Папка cache полностью очищена! 🧹✨")
        except Exception as e:
            print(f"[Cache Error] Ошибка при очистке кэша: {e}")

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================
    def _load_json(self, filepath: str) -> dict:
        if not os.path.exists(filepath):
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_json(self, filepath: str, data: dict):
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[Storage Error] Ошибка записи в {filepath}: {e}")