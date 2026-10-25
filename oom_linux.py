import time
import os
import subprocess

SWAP_FILE = "/var/swap_emergency"
SWAP_SIZE_MB = 512

def get_linux_memory_usage_mb():
    """ Читаем информацию о памяти напрямую из ядра Linux """
    total_mb = 0
    available_mb = 0
    with open("/proc/meminfo", "r") as f:
        for line in f:
            if "MemTotal:" in line:
                total_mb = int(line.split()[1]) / 1024  # Переводим КБ в МБ
            elif "MemAvailable:" in line:
                available_mb = int(line.split()[1]) / 1024
                
    used_mb = total_mb - available_mb
    return total_mb, used_mb

def create_emergency_swap():
    if not os.path.exists(SWAP_FILE):
        print(f"Создание аварийного Swap файла на {SWAP_SIZE_MB}MB...")
        subprocess.run(["fallocate", "-l", f"{SWAP_SIZE_MB}M", SWAP_FILE], check=True)
        subprocess.run(["chmod", "600", SWAP_FILE], check=True)
        subprocess.run(["mkswap", SWAP_FILE], check=True)

def is_swap_active():
    try:
        with open("/proc/swaps", "r") as f:
            return SWAP_FILE in f.read()
    except Exception:
        return False

# Инициализация аварийного swap
try:
    create_emergency_swap()
except Exception as e:
    print(f"Не удалось создать swap (нужны права root): {e}")

print("OOM Guard запущен (Linux). Мониторинг RAM...")

while True:
    try:
        total_mb, used_mb = get_linux_memory_usage_mb()
        
        # Динамический порог: ровно 90% от общей памяти конкретного устройства
        TRIGGER_MB = total_mb * 0.9

        if used_mb >= TRIGGER_MB and not is_swap_active():
            print("OOM. Старт аварийного Swap")
            subprocess.run(["swapon", SWAP_FILE], check=True)
            print("Аварийный Swap успешно активирован!")
            
        time.sleep(1) # Проверка каждую секунду
        
    except Exception as e:
        print(f"Ошибка в OOM Guard: {e}")
        time.sleep(3)