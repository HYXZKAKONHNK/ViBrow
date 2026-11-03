const std = @import("std");
const lexer = @import("lexer.zig");
const parser = @import("parser.zig");
const compiler = @import("compiler.zig");
const vm = @import("vm.zig");
const js = @import("js_value.zig");

const MAX_MEMORY_PER_TAB = 20 * 1024 * 1024;

// ─────────────────────────────────────────────────────────────
// Кэш результатов. Храним ТОЛЬКО скалярные данные — никаких
// указателей в heap VM, потому что VM умирает до возврата из
// executeInternal. Тем самым кэш безопасен для чтения везде.
// ─────────────────────────────────────────────────────────────

const CachedResult = struct {
    as_number: f64,
    is_number: bool,
    tag: u8,
};

fn failResult() CachedResult {
    return .{
        .as_number = std.math.nan(f64),
        .is_number = false,
        .tag = @intFromEnum(js.getTag(js.JS_NAN)),
    };
}

const CacheEntry = struct {
    key: []u8,
    value: CachedResult,
};

var result_cache: ?std.ArrayList(CacheEntry) = null;
const MAX_CACHE_ENTRIES = 2048;

fn cacheGet(key: []const u8) ?CachedResult {
    const cache = result_cache orelse return null;
    for (cache.items) |entry| {
        if (std.mem.eql(u8, entry.key, key)) return entry.value;
    }
    return null;
}

fn cachePut(key: []const u8, value: CachedResult) void {
    if (result_cache == null) {
        result_cache = std.ArrayList(CacheEntry).init(std.heap.page_allocator);
    }
    const cache = &result_cache.?;
    if (cache.items.len >= MAX_CACHE_ENTRIES) return;
    const duped = std.heap.page_allocator.dupe(u8, key) catch return;
    cache.append(.{ .key = duped, .value = value }) catch {
        std.heap.page_allocator.free(duped);
    };
}

// ─────────────────────────────────────────────────────────────
// Полный pipeline: lexer → parser → compiler → VM.
// Арена поверх GPA: все промежуточные AST/байткоды/строки
// освобождаются одним deinit, а GPA ограничивает суммарную память.
// ─────────────────────────────────────────────────────────────

fn executeInternal(js_code: []const u8) CachedResult {
    if (cacheGet(js_code)) |hit| return hit;

    var gpa = std.heap.GeneralPurposeAllocator(.{
        .enable_memory_limit = true,
        .memory_limit = MAX_MEMORY_PER_TAB,
    }){};
    defer _ = gpa.deinit();

    var arena = std.heap.ArenaAllocator.init(gpa.allocator());
    defer arena.deinit();
    const allocator = arena.allocator();

    const fail = failResult();

    const tokens = lexer.tokenize(allocator, js_code) catch {
        cachePut(js_code, fail);
        return fail;
    };

    const ast = parser.parseProgram(allocator, tokens) catch {
        cachePut(js_code, fail);
        return fail;
    };

    const image = compiler.compileProgram(allocator, ast) catch {
        cachePut(js_code, fail);
        return fail;
    };

    var machine = vm.VM.init(allocator, &image) catch {
        cachePut(js_code, fail);
        return fail;
    };
    defer machine.deinit();

    const value = machine.runMain() catch {
        cachePut(js_code, fail);
        return fail;
    };

    // Распаковываем JsValue В СКАЛЯРЫ до того, как arena.deinit()
    // освободит heap VM. Так кэш и возврат безопасны.
    const out: CachedResult = .{
        .as_number = js.toNumber(value),
        .is_number = js.isNumber(value),
        .tag = @intFromEnum(js.getTag(value)),
    };
    cachePut(js_code, out);
    return out;
}

// ─────────────────────────────────────────────────────────────
// C-API для ctypes (Python)
// ─────────────────────────────────────────────────────────────

export fn vijs_execute(js_code_ptr: [*:0]const u8) callconv(.C) f64 {
    return executeInternal(std.mem.span(js_code_ptr)).as_number;
}

export fn vijs_is_number(js_code_ptr: [*:0]const u8) callconv(.C) bool {
    return executeInternal(std.mem.span(js_code_ptr)).is_number;
}

export fn vijs_get_type(js_code_ptr: [*:0]const u8) callconv(.C) u8 {
    return executeInternal(std.mem.span(js_code_ptr)).tag;
}

// ─────────────────────────────────────────────────────────────
// Self-tests (zig run src/engine.zig)
// ─────────────────────────────────────────────────────────────

pub fn main() !void {
    std.debug.print("╔═══════════════════════════════════════╗\n", .{});
    std.debug.print("║  ViBrow JS Engine — NaN Boxing Test   ║\n", .{});
    std.debug.print("╚═══════════════════════════════════════╝\n\n", .{});

    const cases = [_]struct {
        code: [:0]const u8,
        expected: f64,
    }{
        .{ .code = "5 + 3", .expected = 8.0 },
        .{ .code = "10 * 2 - 5", .expected = 15.0 },
        .{ .code = "(3 + 7) * 2", .expected = 20.0 },
        .{ .code = "100 / 5 + 10", .expected = 30.0 },
        .{ .code = "2 + 3 * 4", .expected = 14.0 },
        .{ .code = "(2 + 3) * 4", .expected = 20.0 },
        .{ .code = "-5 + 3", .expected = -2.0 },
        .{ .code = "7 % 3", .expected = 1.0 },
        .{ .code = "2 ** 10", .expected = 1024.0 },
        .{ .code = "2 ** 3 ** 2", .expected = 512.0 },
        .{ .code = "// comment\n6 * 7", .expected = 42.0 },
        .{ .code = "/* block */ 1 + 1", .expected = 2.0 },
    };

    var passed: usize = 0;
    for (cases) |tc| {
        const got = vijs_execute(tc.code.ptr);
        const ok = got == tc.expected;
        if (ok) passed += 1;
        const mark: []const u8 = if (ok) "✓" else "✗";
        std.debug.print("{s} {s} = {d}", .{ mark, tc.code, got });
        if (!ok) std.debug.print(" (ожидалось {d})", .{tc.expected});
        std.debug.print("\n", .{});
    }

    std.debug.print("\n=== Результаты: {}/{} тестов прошло ===\n", .{ passed, cases.len });

    std.debug.print("\n=== Тест типов ===\n", .{});
    std.debug.print("5 + 3 — это число? {s}\n", .{
        if (vijs_is_number("5 + 3")) "да" else "нет",
    });
    std.debug.print("Тип результата (0=число): {}\n", .{vijs_get_type("5 + 3")});
}
