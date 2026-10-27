# Запуск и установка ViBrow:
Чтобы скачать и запустить ViBrow вам надо выполнить 3 части
1. Установка
Через Git: Откройте терминал (или cmd), ждите загрузки и введите git clone https://www.github.com/HYXZKAKONHNK/ViBrow, нажмите enter, после выполнения первой команды выполните cd ViBrow, далее нажмите Enter
Вручную: Перейдите на страницу репозитория, нажмите на зелёную кнопку Code. Там появится меню и выберите Download ZIP в самом низу. Создайте папку с любым именем, зайдите в загрузки, нажмите на тот скачанный файл ПКМ и выберите "Извлечь всё". Скопируйте путь папки и через ctrl + V скопируйте путь туда
2. Запуск
На Windows: Найдите в той созданной папке файл под названием start.bat и включите его (Два раза ЛКМ) или откройте win + R, там cmd и cd (путь к папке). После этого введите python viengine.py
На Linux или MacOS: Откройте терминал в папке с проектом и запустите файл через терминал. Введите там команду python3 viengine.py
3. Работа
У вас всё запустилось! Теперь можете спокойно открывать свои любимые сайты

# Ошибки и их исправление
Если у вас появилась ошибка ModuleNotFoundError: No module named 'tkinter': Введите в терминале команду sudo apt install python3-tk или для юзеров arch (фембоев) sudo pacman -S tk
Если команда python/python3 не найдена, то установите python (10+ версии!!!). При старте обязательно должна стоять галочка "Add python.exe to PATH"

# Для пользователей MacOS
Пожалуйста, скомпилируйте себе сами компилятор для запуска. Я бы сам скомпилировал, но дело в том, что я на Windows, а он не может работать с MacOS. Скачайте Zig и введите эти команды (зависит от версии):
zig build-lib -dynamic src\engine.zig -target x86_64-macos.12 -O ReleaseFast -femit-bin=native\macos_x64\libvijs_engine.dylib (папка macos_x64)
zig build-lib -dynamic src\engine.zig -target aarch64-macos.12 -O ReleaseFast -femit-bin=native\macos_arm64\libvijs_engine.dylib (папка macos_arm64)
(перед этим в папке vijs_engine создайте папку native. а там папку macos_arm64 или macos_x64)
