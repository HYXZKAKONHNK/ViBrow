const std = @import("std");
const js = @import("js_value.zig");

pub fn main() !void {
    std.debug.print("=== ViBrow NaN Boxing Test ===\n\n", .{});

    // 1. Числа
    const num1 = js.fromNumber(42.5);
    const num2 = js.fromNumber(-3.14);
    const num3 = js.fromNumber(0);
    const inf = js.fromNumber(std.math.inf(f64));
    
    std.debug.print("num1 = 42.5:  isNumber={}, value={d}\n", .{js.isNumber(num1), js.getNumber(num1)});
    std.debug.print("num2 = -3.14: isNumber={}, value={d}\n", .{js.isNumber(num2), js.getNumber(num2)});
    std.debug.print("num3 = 0:     isNumber={}, value={d}\n", .{js.isNumber(num3), js.getNumber(num3)});
    std.debug.print("inf:          isNumber={}, value=", .{js.isNumber(inf)});
    js.dump(inf);
    std.debug.print("\n", .{});

    // 2. undefined, null
    std.debug.print("\nundefined: isUndefined={}, size={} bytes\n", .{js.isUndefined(js.UNDEFINED), @sizeOf(js.JsValue)});
    std.debug.print("null:      isNull={},      size={} bytes\n", .{js.isNull(js.NULL), @sizeOf(js.JsValue)});

    // 3. Булевы
    const t = js.fromBool(true);
    const f = js.fromBool(false);
    std.debug.print("\ntrue:  isBool={}, toBoolean={}, value=", .{js.isBool(t), js.toBoolean(t)});
    js.dump(t);
    std.debug.print("\nfalse: isBool={}, toBoolean={}, value=", .{js.isBool(f), js.toBoolean(f)});
    js.dump(f);

    // 4. NaN
    const nan_val = js.fromNumber(std.math.nan(f64));
    std.debug.print("\n\nNaN: isNumber={}, tag={}\n", .{js.isNumber(nan_val), js.getTag(nan_val)});

    // 5. Объект (имитация указателя)
    var fake_object: u64 = 0xDEADBEEF;
    const obj = js.fromObject(&fake_object);
    std.debug.print("\nObject: isObject={}, ptr={x}\n", .{js.isObject(obj), @intFromPtr(js.getObjectPtr(obj))});

    // 6. Размер
    std.debug.print("\n=== Экономия памяти ===\n", .{});
    std.debug.print("Размер одного JsValue: {} байт (вместо 16 в наивной реализации)\n", .{@sizeOf(js.JsValue)});
    std.debug.print("Стек на 256 значений: {} байт (вместо 4096)\n", .{256 * @sizeOf(js.JsValue)});
    std.debug.print("Экономия: 50%%\n", .{});
}
