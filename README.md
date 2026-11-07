# ViBrow
ViBrow – Быстрый и современный браузер, основанный на кастомном движке viengine
Он написан на языке программирования Python, без каких-либо сторонних библиотек. Работает на чистом python. Весит около 44МБ распакованным
# Поддерживает операционные системы: 
Windows 11 (все модификации, x64 / ARM64) — с актуальными версиями Python 3.10+ и аппаратным ускорением отрисовки окон.
Windows 10 (все модификации, x64) — при условии нормальной работы диспетчера окон и отсутствия сильной фоновой нагрузки.
Linux (современные дистрибутивы с легковесным окружением, например: Ubuntu 22.04 / 24.04 LTS, Debian 12, Arch Linux с XFCE, MATE или KDE Plasma) — на Linux Tkinter и сокеты работают очень шустро, а накладные расходы ОС минимальны. Работает также на устройствах типа: Raspberry Pi, Yandex Alisa, Orange Pi, Banana Pi, Radxa Zero, FPGA и прочими микрокомпьютерами
macOS (версии macOS 12 Monterey, 13 Ventura, 14 Sonoma, 15 Sequoia и новее на процессорах Apple Silicon M1/M2/M3/M4) — за счет высокой производительности однопоточных вычислений процессоров Apple Silicon интерпретатор JS и отрисовка интерфейса будут работать максимально гладко.
# Работает на основе встроенных библиотек:
Tkinter, socket, ssl, threading, urllib,
# Уникальные функции
В ViBrow также присутствуют защитники от OOM (ошибки Out Of Memory), они работают в фоновых процессах и если 90% оперативной памяти занято, создают аварийный файл подкачки на 512МБ. Сначала включается фоновый процесс, который определяет операционную систему, когда он понял какая это ОС он открывает соответствующий код для этой ОС. Это очень важно для микрокомпьютеров
Также в движке был реализован NaN Boxing, переход на Zig обусловлен тем, что я стремлюсь к скорости и компактности, что Zig и может дать. Переход на Zig был только в движке JavaScript (JS)

# Инструкция по установке и запуске ViBrow 
[INSTRUCTIONS.md](INSTRUCTIONS.md)

# Лицензия
Этот проект распространяется под лицензией **GNU Affero General Public License v3.0**.
Подробнее см. файл [LICENSE](LICENSE).

# Упаковка файлов html в приложение
ViForge – [упаковщик](viforge.py).

Запуск как собранное приложение: python viforge.py --production. 

Запуск как Studio (IDE): python viforge.py. 

# Архитектура JS движка
JavaScript движок браузера ViBrow (viengine) является VMIT (Virtual Machine Interpretive Type) ну или виртуальная машина интерпретируемого типа

# In english
# ViBrow

A lightweight, custom web browser written in pure Python and Zig, engineered specifically for low-resource microcomputers (Raspberry Pi, Orange Pi, older hardware). 

ViBrow runs entirely on standard libraries (Tkinter, socket, ssl, threading) without a single third-party dependency, consuming only **30-65 MB of RAM**.

## Core Features
* **Custom Layout Engines:** Built from scratch DOM parsing and CSS rendering.
* **VMIT JS Engine:** A custom interpreted JavaScript Virtual Machine (`vijs_engine`) featuring **NaN Boxing** for optimal speed and memory layout. Parts of the JS engine are written in **Zig** for bare-metal performance.
* **Ultra-Low Hardware Requirements:** Runs smoothly on a single-core 700MHz CPU and 200MB LPDDR1 RAM.
* **Built-in OOM Protection:** Active background guard processes that automatically spin up a emergency swap space if RAM usage crosses 90% (tailored per OS: Linux, Windows, macOS).
* **Privacy & Utility:** Multi-tab interface, local caching, cookie management, and an integrated proxy bridge.
* **ViForge Ecosystem:** Includes a built-in bundler (`viforge.py`) to package HTML files into standalone apps or run as a local IDE Studio.

## OS Support
* **Linux:** (Ubuntu, Debian, Arch with light DEs like XFCE/MATE) – maximum efficiency, highly responsive Tkinter rendering.
* **Microcomputers:** Raspberry Pi, Orange Pi, Banana Pi, Radxa Zero, etc.
* **Windows & macOS:** Full support for Windows 10/11 and Apple Silicon (M1-M4) with hardware acceleration enabled.

## Architecture Short Note
Unlike bloated Chromium-based setups, ViBrow relies on explicit single-threaded parsing efficiency and zero heavy dependencies. The JS engine transitions key execution paths to Zig to overcome Python's interpretation overhead while maintaining a tiny footprint.

## License
Distributed under the GNU Affero General Public License v3.0 (AGPL-3.0).

вот вам английский американские бургеры из реддита

![логотип](resourses/ViBrow_logof.png)
