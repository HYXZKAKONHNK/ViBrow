const std = @import("std");
const lexer = @import("lexer.zig");
const parser = @import("parser.zig");
const compiler = @import("compiler.zig");
const vm = @import("vm.zig");

const MAX_MEMORY_PER_TAB = 120 * 1024 * 1024; // 120 МБ

const EngineError = error{
    ParseError,
    CompileError,
    RuntimeError,
    OutOfMemory,
};

/// Главная функция, которую вызывает Python
/// Выполняет JS код и возвращает числовой результат (для начала)
export fn vijs_execute(js_code_ptr: [*:0]const u8) callconv(.C) i32 {
    // 1. Создаем аллокатор с лимитом памяти
    var gpa = std.heap.GeneralPurposeAllocator(.{
        .enable_memory_limit = true,
        .memory_limit = MAX_MEMORY_PER_TAB,
    }){};
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();

    // 2. Преобразуем C-строку в Zig-срез
    const js_code = std.mem.span(js_code_ptr);
    
    // 3. Лексический анализ
    const tokens = lexer.tokenize(allocator, js_code) catch |err| {
        std.debug.print("Lexer error: {}\n", .{err});
        return -1;
    };
    defer allocator.free(tokens);

    // 4. Парсинг в AST
    const ast = parser.parse(allocator, tokens) catch |err| {
        std.debug.print("Parser error: {}\n", .{err});
        return -1;
    };
    defer ast.destroy(allocator);

    // 5. Компиляция в байткод
    const bytecode = compiler.compile(allocator, ast) catch |err| {
        std.debug.print("Compiler error: {}\n", .{err});
        return -1;
    };
    defer allocator.free(bytecode);

    // 6. Выполнение байткода в VM
    const result = vm.execute(allocator, bytecode) catch |err| {
        std.debug.print("VM error: {}\n", .{err});
        return -1;
    };

    // Возвращаем результат (пока только целые числа)
    if (result == .number) {
        return @as(i32, @intFromFloat(result.number));
    }
    return 0;
}

// Тестовая функция для проверки из командной строки
pub fn main() !void {
    const result = vijs_execute("5 + 3 * 2");
    std.debug.print("Result: {}\n", .{result}); // Должно быть 11
}
