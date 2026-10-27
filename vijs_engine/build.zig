const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Создаем динамическую библиотеку для Python
    const lib = b.addSharedLibrary(.{
        .name = "vijs_engine",
        .root_source_file = .{ .path = "src/engine.zig" },
        .target = target,
        .optimize = optimize,
    });

    // Важно для ARM/микрокомпьютеров: строгий контроль размера
    lib.bundle_compiler_rt = true;
    
    b.installArtifact(lib);
}
