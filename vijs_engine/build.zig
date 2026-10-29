const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Zig 0.17: addSharedLibrary удалён — вместо него addLibrary(.{ .linkage = .dynamic }).
    // target/optimize теперь живут в Module (root_module), а не в шаге компиляции.
    const lib = b.addLibrary(.{
        .name = "vijs_engine",
        .linkage = .dynamic,
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/engine.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });

    // Строгий контроль размера бинарника для ARM/микрокомпьютеров.
    // В 0.17 это публичное поле (в 0.16 был приватным).
    lib.bundle_compiler_rt = true;

    b.installArtifact(lib);

    // NaN-boxing smoke-тест как исполняемый артефакт: zig build js-test -Drun
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
}
