const std = @import("std");
const lexer = @import("lexer.zig");
const parser = @import("parser.zig");
const compiler = @import("compiler.zig");
const vm = @import("vm.zig");
const js = @import("js_value.zig");

// ═══════════════════════════════════════════════════════════════
// НАСТРОЙКИ ДВИЖКА ViBrow
// ═══════════════════════════════════════════════════════════════

/// Максимум памяти на одну вкладку (как ты хотел — 20 МБ минимум)
const MAX_MEMORY_PER_TAB = 20 * 1024 * 1024;

/// Типы ошибок, которые может вернуть движок
const EngineError = error{
    LexError,       // Лексер не смог разобрать код
    ParseError,     // Парсер не смог построить дерево
    CompileError,   // Компилятор не смог сделать байткод
    RuntimeError,   // VM не смогла выполнить
    OutOfMemory,    // Закончилась память (сработала защита)
};

// ═══════════════════════════════════════════════════════════════
// ВНУТРЕННЯЯ ФУНКЦИЯ — выполняет полный pipeline
// ═══════════════════════════════════════════════════════════════

/// Выполняет JS-код и возвращает упакованный JsValue (u64).
/// Возвращает JS_NAN при любой ошибке.
fn executeInternal(js_code: []const u8) js.JsValue {
    // Создаём аллокатор с защитой от переполнения памяти.
    // GeneralPurposeAllocator (GPA) — это лучший аллокатор Zig:
    // он ловит утечки памяти и переполнения в debug-режиме.
    var gpa = std.heap.GeneralPurposeAllocator(.{
        .enable_memory_limit = true,
        .memory_limit = MAX_MEMORY_PER_TAB,
    }){};
    
    // defer гарантирует, что память освободится при выходе из функции.
    // Аналог try/finally в Python.
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();

    // Шаг 1: Лексер — разбиваем код на токены
    const tokens = lexer.tokenize(allocator, js_code) catch |err| {
        std.debug.print("[ViBrow] Lex error: {}\n", .{err});
        return js.JS_NAN;
    };
    defer allocator.free(tokens); // Освобождаем массив токенов

    // Шаг 2: Парсер — строим AST (дерево)
    const ast = parser.parse(allocator, tokens) catch |err| {
        std.debug.print("[ViBrow] Parse error: {}\n", .{err});
        return js.JS_NAN;
    };
    defer ast.destroy(allocator); // Освобождаем дерево

    // Шаг 3: Компилятор — превращаем AST в байткод
    const bytecode = compiler.compile(allocator, ast) catch |err| {
        std.debug.print("[ViBrow] Compile error: {}\n", .{err});
        return js.JS_NAN;
    };
    defer allocator.free(bytecode); // Освобождаем байткод

    // Шаг 4: VM — выполняем байткод и получаем JsValue
    const result = vm.execute(allocator, bytecode) catch |err| {
        std.debug.print("[ViBrow] Runtime error: {}\n", .{err});
        return js.JS_NAN;
    };

    return result;
}

// ═══════════════════════════════════════════════════════════════
// ФУНКЦИИ ДЛЯ PYTHON (через ctypes)
// ═══════════════════════════════════════════════════════════════

/// Главная функция. Python передаёт C-строку, мы возвращаем число.
/// callconv(.C) — обязательно для совместимости с Python/ctypes.
export fn vijs_execute(js_code_ptr: [*:0]const u8) callconv(.C) f64 {
    // Преобразуем C-строку (null-terminated) в Zig-срез
    const js_code = std.mem.span(js_code_ptr);
    
    // Выполняем весь pipeline
    const result = executeInternal(js_code);
    
    // Преобразуем JsValue в обычное число f64.
    // Если результат не число (например, undefined) — вернётся NaN.
    return js.toNumber(result);
}

/// Проверяет, является ли результат числом.
/// Полезно для Python, чтобы понять, успешно ли выполнился код.
export fn vijs_is_number(js_code_ptr: [*:0]const u8) callconv(.C) bool {
    const js_code = std.mem.span(js_code_ptr);
    const result = executeInternal(js_code);
    return js.isNumber(result);
}

/// Возвращает тег типа результата (для отладки).
/// 0 = number, 1 = undefined, 2 = null, 3 = false, 4 = true, 5 = NaN, 6 = object, 7 = string
export fn vijs_get_type(js_code_ptr: [*:0]const u8) callconv(.C) u8 {
    const js_code = std.mem.span(js_code_ptr);
    const result = executeInternal(js_code);
    return @intFromEnum(js.getTag(result));
}

// ═══════════════════════════════════════════════════════════════
// ТЕСТ БЕЗ PYTHON (запуск: zig run src/engine.zig)
// ═══════════════════════════════════════════════════════════════

pub fn main() !void {
    std.debug.print("╔═══════════════════════════════════════╗\n", .{});
    std.debug.print("║  ViBrow JS Engine — NaN Boxing Test   ║\n", .{});
    std.debug.print("╚═══════════════════════════════════════╝\n\n", .{});

    // Тестовые примеры
    const test_cases = [_]struct {
        code: [:0]const u8,
        expected: f64,
    }{
        .{ .code = "5 + 3", .expected = 8.0 },
        .{ .code = "10 * 2 - 5", .expected = 15.0 },
        .{ .code = "(3 + 7) * 2", .expected = 20.0 },
        .{ .code = "100 / 5 + 10", .expected = 30.0 },
        .{ .code = "2 + 3 * 4", .expected = 14.0 }, // Приоритет операторов
        .{ .code = "(2 + 3) * 4", .expected = 20.0 },
    };

    var passed: usize = 0;
    
    for (test_cases) |test| {
        const result = vijs_execute(test.code);
        const is_correct = result == test.expected;
        if (is_correct) passed += 1;
        
        const status = if (is_correct) "✓" else "✗";
        std.debug.print("{s} {s} = {d}", .{ status, test.code, result });
        
        if (!is_correct) {
            std.debug.print(" (ожидалось: {d})", .{test.expected});
        }
        std.debug.print("\n", .{});
    }

    std.debug.print("\n=== Результаты: {}/{} тестов прошло ===\n", .{ passed, test_cases.len });

    // Тест проверки типа
    std.debug.print("\n=== Тест типов ===\n", .{});
    std.debug.print("5 + 3 — это число? {s}\n", .{
        if (vijs_is_number("5 + 3")) "да" else "нет"
    });
    std.debug.print("Тип результата (0=число): {}\n", .{
        vijs_get_type("5 + 3")
    });
}

// Тестовая функция для проверки из командной строки
pub fn main() !void {
    const result = vijs_execute("5 + 3 * 2");
    std.debug.print("Result: {}\n", .{result}); // Должно быть 11
}
