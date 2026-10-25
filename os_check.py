import sys
import subprocess

def os_check():
    os = sys.platform
    if os == "win32":
        subprocess.Popen([sys.executable, "oom_win32.py"])
    elif os == "linux":
        subprocess.Popen([sys.executable, "oom_linux.py"])
    elif os == "darwin":
        subprocess.Popen([sys.executable, "oom_macos.py"])
    else:
        print("Что-за ОС? Ты на прошивке биоса сидишь?")

os_check()