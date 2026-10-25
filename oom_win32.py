import time
import subprocess
import ctypes

# Определяем структуру для получения памяти через Windows API
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullExtendedVirtual", ctypes.c_ulonglong),
    ]

def get_windows_memory_usage():
    """ Получает общий объем и сколько занято МБ в реальном времени """
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    
    total_mb = stat.ullTotalPhys / (1024 * 1024)
    free_mb = stat.ullAvailPhys / (1024 * 1024)
    used_mb = total_mb - free_mb
    return total_mb, used_mb

def expand_windows_pagefile():
    """ Создает / расширяет аварийный файл подкачки на 512 МБ в абсолютной тишине """
    ps_script = (
        "$cs = Get-CimInstance Win32_ComputerSystem;"
        "if ($cs.AutomaticManagedPagefile) { $cs.AutomaticManagedPagefile = $false; $cs | Set-CimInstance };"
        "$pf = Get-CimInstance -ClassName Win32_PageFileSetting;"
        "if ($pf) { $pf | Remove-CimInstance };"
        "New-CimInstance -ClassName Win32_PageFileSetting -Property @{ Name = 'C:\\pagefile.sys'; InitialSize = 512; MaximumSize = 512 }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

if __name__ == "__main__":
    swap_activated = False

    while True:
        try:
            total_mb, used_mb = get_windows_memory_usage()
            
            # Динамический порог: 90% от общей памяти конкретного ПК
            trigger_limit = total_mb * 0.9 

            # Если сожрали больше 90% и аварийный подкачки еще не касались
            if used_mb >= trigger_limit and not swap_activated:
                expand_windows_pagefile()
                swap_activated = True  # Чтобы не дергать PowerShell каждую секунду
                
            time.sleep(1) # Проверка каждую секунду в фоне
            
        except Exception:
            time.sleep(3)