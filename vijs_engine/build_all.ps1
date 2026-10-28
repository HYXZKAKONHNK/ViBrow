$ErrorActionPreference = "Stop"
$src = "src/engine.zig"

$targets = @(
    @{sub="windows_x64";  target="x86_64-windows-gnu";       file="vijs_engine.dll";         extra=@()},
    @{sub="windows_arm64";target="aarch64-windows-gnu";      file="vijs_engine.dll";         extra=@()},
    @{sub="linux_x64";    target="x86_64-linux-gnu.2.17";    file="libvijs_engine.so";       extra=@()},
    @{sub="linux_arm64";  target="aarch64-linux-gnu.2.17";   file="libvijs_engine.so";       extra=@()},
    @{sub="linux_armv7";  target="arm-linux-gnueabihf.2.17"; file="libvijs_engine.so";       extra=@()},
    @{sub="linux_armv6";  target="arm-linux-gnueabihf.2.17"; file="libvijs_engine.so";       extra=@("-mcpu=arm1176jzf_s")},
    @{sub="macos_x64";    target="x86_64-macos.12";          file="libvijs_engine.dylib";    extra=@()},
    @{sub="macos_arm64";  target="aarch64-macos.12";         file="libvijs_engine.dylib";    extra=@()}
)

foreach ($t in $targets) {
    $outDir = "native\$($t.sub)"
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $outFile = "$outDir\$($t.file)"
    
    Write-Host "`n→ Сборка $($t.sub)..." -ForegroundColor Cyan
    
    $args = @("build-lib", "-dynamic", $src, "-target", $t.target, "-O", "ReleaseFast", "-femit-bin=$outFile") + $t.extra
    
    try {
        & zig @args
        Write-Host "✓ $($t.sub) готова: $outFile" -ForegroundColor Green
    } catch {
        Write-Host "✗ $($t.sub) ОШИБКА: $_" -ForegroundColor Red
    }
}

Write-Host "`n🎉 Готово! Папка native/ готова к упаковке в релиз." -ForegroundColor Green