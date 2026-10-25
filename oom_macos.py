import time
import subprocess
import re

def get_macos_memory_usage_mb():
    """ Получаем общий объем и занятую память на macOS через системные утилиты """
    try:
        # 1. Узнаем общий объем памяти в байтах и переводим в МБ
        total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip())
        total_mb = total_bytes / (1024 * 1024)
        
        # 2. Узнаем размер страницы памяти (обычно 4096 байт)
        page_size = int(subprocess.check_output(["sysctl", "-n", "hw.pagesize"]).decode().strip())
        
        # 3. Парсим vm_stat для получения доступной памяти
        vm_output = subprocess.check_output(["vm_stat"]).decode()
        
        pages_free = 0
        pages_inactive = 0
        pages_speculative = 0
        
        for line in vm_output.split("\n"):
            if "Pages free" in line:
                pages_free = int(re.findall(r'\d+', line)[0])
            elif "Pages inactive" in line:
                pages_inactive = int(re.findall(r'\d+', line)[0])
            elif "Pages speculative" in line:
                pages_speculative = int(re.findall(r'\d+', line)[0])
                
        # Считаем доступную память (free + inactive + speculative)
        available_bytes = (pages_free + pages_inactive + pages_speculative) * page_size
        available_mb = available_bytes / (1024 * 1024)
        
        used_mb = total_mb - available_mb
        return total_mb, used_mb
    except Exception:
        return 0, 0

def is_swap_active():
    """ Проверяем использование встроенного Swap на macOS """
    try:
        swap_output = subprocess.check_output(["sysctl", "vm.swapusage"]).decode()
        # Вывод выглядит примерно так: vm.swapusage: total = 1024.00M  used = 120.50M  free = 903.50M
        match = re.search(r'used\s*=\s*([\d.]+)', swap_output)
        if match:
            used_swap = float(match.group(1))
            return used_swap > 0
    except Exception:
        pass
    return False

if __name__ == "__main__":
    print("OOM Guard запущен (macOS). Мониторинг RAM...")

    while True:
        try:
            total_mb, used_mb = get_macos_memory_usage_mb()
            
            if total_mb > 0:
                # Динамический порог: 90% от общего объема памяти мака
                trigger_mb = total_mb * 0.9

                # Если память забита под 90% и более
                if used_mb >= trigger_mb:
                    print(f"Внимание! Память перегружена: {used_mb:.1f} / {total_mb:.1f} МБ")
                    if is_swap_active():
                        print("macOS уже задействовала системный Swap!")
                    else:
                        print("macOS управляет ресурсами в штатном режиме.")
            
            time.sleep(1) # Проверка каждую секунду
            
        except Exception as e:
            print(f"Ошибка в OOM Guard (macOS): {e}")
            time.sleep(3)