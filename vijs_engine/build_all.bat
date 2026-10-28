@echo off
chcp 65001 >nul
echo ==========================================
echo   ViBrow JS Engine - Cross-Platform Build
echo ==========================================
echo.

mkdir native\windows_x64 2>nul
mkdir native\windows_arm64 2>nul
mkdir native\linux_x64 2>nul
mkdir native\linux_arm64 2>nul
mkdir native\linux_armv7 2>nul
mkdir native\linux_armv6 2>nul
mkdir native\macos_x64 2>nul
mkdir native\macos_arm64 2>nul

echo [1/8] Windows x64...
zig build-lib -dynamic src\engine.zig -target x86_64-windows-gnu -O ReleaseFast -femit-bin=native\windows_x64\vijs_engine.dll

echo [2/8] Windows ARM64...
zig build-lib -dynamic src\engine.zig -target aarch64-windows-gnu -O ReleaseFast -femit-bin=native\windows_arm64\vijs_engine.dll

echo [3/8] Linux x64...
zig build-lib -dynamic src\engine.zig -target x86_64-linux-gnu.2.17 -O ReleaseFast -femit-bin=native\linux_x64\libvijs_engine.so

echo [4/8] Linux ARM64...
zig build-lib -dynamic src\engine.zig -target aarch64-linux-gnu.2.17 -O ReleaseFast -femit-bin=native\linux_arm64\libvijs_engine.so

echo [5/8] Linux ARMv7...
zig build-lib -dynamic src\engine.zig -target arm-linux-gnueabihf.2.17 -O ReleaseFast -femit-bin=native\linux_armv7\libvijs_engine.so

echo [6/8] Linux ARMv6 (Raspberry Pi Zero)...
zig build-lib -dynamic src\engine.zig -target arm-linux-gnueabihf.2.17 -mcpu=arm1176jzf_s -O ReleaseFast -femit-bin=native\linux_armv6\libvijs_engine.so

echo [7/8] macOS Intel (может упасть на Windows, это нормально)...
zig build-lib -dynamic src\engine.zig -target x86_64-macos.12 -O ReleaseFast -femit-bin=native\macos_x64\libvijs_engine.dylib

echo [8/8] macOS Apple Silicon (может упасть на Windows, это нормально)...
zig build-lib -dynamic src\engine.zig -target aarch64-macos.12 -O ReleaseFast -femit-bin=native\macos_arm64\libvijs_engine.dylib

echo.
echo ==========================================
echo   Done! Check the native\ folder.
echo ==========================================
pause