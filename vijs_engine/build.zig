const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Динамическая библиотека: Python ctypes грузит zig-out/lib/libvijs_engine.so
    const lib = b.addLibrary(.{
        .name = "vijs_engine",
        .linkage = .dynamic,
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/engine.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    // bundle_compiler_rt в 0.17.0 — это ?bool; для dynamic lib компилятор
    // и так включает compiler-rt по умолчанию. Явный true безвреден,
    // но null ближе к дефолтному поведению.
    // lib.bundle_compiler_rt = null;

    b.installArtifact(lib);

    // js_value.zig NaN-boxing smoke test
    const js_test_exe = b.addExecutable(.{
        .name = "js_value_test",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/js_value_test.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const run_js_test = b.addRunArtifact(js_test_exe);
    const js_test_step = b.step("js-test", "Run the NaN-boxing smoke test");
    js_test_step.dependOn(&run_js_test.step);

    // Полный self-test из engine.zig
    const engine_test_exe = b.addExecutable(.{
        .name = "engine_test",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/engine.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const run_engine_test = b.addRunArtifact(engine_test_exe);
    const engine_test_step = b.step("engine-test", "Run engine.zig self-tests");
    engine_test_step.dependOn(&run_engine_test.step);
}
