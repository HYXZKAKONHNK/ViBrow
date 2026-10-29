const std = @import("std");

/// JsValue — любое значение JavaScript, упакованное в 64 бита.
/// Это ядро движка. Никаких аллокаций, никаких указателей на тип.
/// Просто один u64, который можно копировать, сравнивать, передавать.
pub const JsValue = u64;

// ─────────────────────────────────────────────────────────────
// Константы для упаковки
// ─────────────────────────────────────────────────────────────

/// "Тихий" NaN (Quiet NaN) — базовая метка для всех нечисловых значений.
/// Экспонента = 0x7FF (все единицы), старший бит мантиссы = 1.
const QNAN: u64 = 0x7FF8_0000_0000_0000;

/// Сдвиг для тегов типов (биты 51-48)
const TAG_SHIFT: u6 = 48;

/// Маска для извлечения 48-битной полезной нагрузки (указателя)
const PAYLOAD_MASK: u64 = 0x0000_FFFF_FFFF_FFFF;

/// Маска для извлечения тега типа (биты 51-48)
const TAG_MASK: u64 = 0x000F_0000_0000_0000;

// ─────────────────────────────────────────────────────────────
// Теги типов
// ─────────────────────────────────────────────────────────────

const Tag = enum(u4) {
    number = 0,      // обычное число (не использует NaN-пространство)
    undefined = 1,   // JS undefined
    null = 2,        // JS null
    boolean_false = 3,
    boolean_true = 4,
    js_nan = 5,      // результат 0/0, NaN
    object = 6,      // указатель на объект (48 бит)
    string = 7,      // указатель на строку (48 бит)
    // 8-15 зарезервированы для будущих типов:
    // symbol, function, array, date и т.д.
};

// ─────────────────────────────────────────────────────────────
// Предопределённые значения (константы времени компиляции)
// ─────────────────────────────────────────────────────────────

pub const UNDEFINED: JsValue = QNAN | (@as(u64, @intFromEnum(Tag.undefined)) << TAG_SHIFT);
pub const NULL: JsValue      = QNAN | (@as(u64, @intFromEnum(Tag.null)) << TAG_SHIFT);
pub const FALSE: JsValue     = QNAN | (@as(u64, @intFromEnum(Tag.boolean_false)) << TAG_SHIFT);
pub const TRUE: JsValue      = QNAN | (@as(u64, @intFromEnum(Tag.boolean_true)) << TAG_SHIFT);
pub const JS_NAN: JsValue    = QNAN | (@as(u64, @intFromEnum(Tag.js_nan)) << TAG_SHIFT);

// ─────────────────────────────────────────────────────────────
// Конструкторы (создание JsValue)
// ─────────────────────────────────────────────────────────────

/// Создать JsValue из числа f64.
/// Если число — NaN, возвращаем канонический JS_NAN.
pub fn fromNumber(n: f64) JsValue {
    // Если это NaN, используем нашу каноническую метку
    if (std.math.isNan(n)) {
        return JS_NAN;
    }
    // Иначе просто переинтерпретируем биты f64 как u64
    return @as(u64, @bitCast(n));
}

/// Создать JsValue из булева значения
pub fn fromBool(b: bool) JsValue {
    return if (b) TRUE else FALSE;
}

/// Создать JsValue из указателя на объект
pub fn fromObject(ptr: *anyopaque) JsValue {
    const addr: u64 = @intFromPtr(ptr);
    // Убеждаемся, что указатель помещается в 48 бит
    std.debug.assert(addr <= PAYLOAD_MASK);
    return QNAN | (@as(u64, @intFromEnum(Tag.object)) << TAG_SHIFT) | addr;
}

/// Создать JsValue из указателя на строку
pub fn fromString(ptr: *anyopaque) JsValue {
    const addr: u64 = @intFromPtr(ptr);
    std.debug.assert(addr <= PAYLOAD_MASK);
    return QNAN | (@as(u64, @intFromEnum(Tag.string)) << TAG_SHIFT) | addr;
}

// ─────────────────────────────────────────────────────────────
// Проверки типа (очень быстрые — побитовые операции)
// ─────────────────────────────────────────────────────────────

/// Проверить, лежит ли значение в NaN-пространстве (не-chrome QNaN).
/// true — это tagged-значение; false — обычное f64 (число/inf).
fn isQNaN(v: JsValue) bool {
    // Экспонента = all ones и мантисса != 0 → NaN (тихий или сигнальный).
    const exponent = (v >> 52) & 0x7FF;
    if (exponent != 0x7FF) return false;
    const mantissa = v & 0x000F_FFFF_FFFF_FFFF;
    return mantissa != 0;
}

/// Получить тег типа из JsValue
pub fn getTag(v: JsValue) Tag {
    // Обычные числа и ±Infinity не лежат в NaN-пространстве
    if (!isQNaN(v)) return .number;
    // Извлекаем тег из битов 51-48
    const tag_bits: u4 = @truncate((v & TAG_MASK) >> TAG_SHIFT);
    // Тег 0 — "сырой" машинный NaN (например, результат 0/0 без нормализации),
    // 8-15 зарезервированы. Мусор трактуем как js_nan, не паникуем.
    return switch (tag_bits) {
        1 => .undefined,
        2 => .null,
        3 => .boolean_false,
        4 => .boolean_true,
        5 => .js_nan,
        6 => .object,
        7 => .string,
        else => .js_nan,
    };
}

/// Является ли значение числом?
pub fn isNumber(v: JsValue) bool {
    return getTag(v) == .number;
}

/// Является ли значение undefined?
pub fn isUndefined(v: JsValue) bool {
    return v == UNDEFINED;
}

/// Является ли значение null?
pub fn isNull(v: JsValue) bool {
    return v == NULL;
}

/// Является ли значение булевым?
pub fn isBool(v: JsValue) bool {
    return v == TRUE or v == FALSE;
}

/// Является ли значение объектом?
pub fn isObject(v: JsValue) bool {
    return getTag(v) == .object;
}

/// Является ли значение строкой?
pub fn isString(v: JsValue) bool {
    return getTag(v) == .string;
}

/// Является ли значение null или undefined? (для == в JS)
pub fn isNullOrUndefined(v: JsValue) bool {
    return v == NULL or v == UNDEFINED;
}

// ─────────────────────────────────────────────────────────────
// Извлечение значений (распаковка)
// ─────────────────────────────────────────────────────────────

/// Получить число f64 из JsValue.
/// Вызывать только если isNumber(v) == true.
pub fn getNumber(v: JsValue) f64 {
    std.debug.assert(isNumber(v));
    return @as(f64, @bitCast(v));
}

/// Получить булево значение
pub fn getBool(v: JsValue) bool {
    std.debug.assert(isBool(v));
    return v == TRUE;
}

/// Получить указатель на объект
pub fn getObjectPtr(v: JsValue) *anyopaque {
    std.debug.assert(isObject(v));
    const addr = v & PAYLOAD_MASK;
    return @as(*anyopaque, @ptrFromInt(addr));
}

/// Получить указатель на строку
pub fn getStringPtr(v: JsValue) *anyopaque {
    std.debug.assert(isString(v));
    const addr = v & PAYLOAD_MASK;
    return @as(*anyopaque, @ptrFromInt(addr));
}

// ─────────────────────────────────────────────────────────────
// Приведение типов (как в JavaScript)
// ─────────────────────────────────────────────────────────────

/// Преобразовать в булево (truthy/falsy как в JS)
pub fn toBoolean(v: JsValue) bool {
    switch (getTag(v)) {
        .undefined, .null, .boolean_false, .js_nan => return false,
        .boolean_true => return true,
        .number => {
            const n = getNumber(v);
            return n != 0 and !std.math.isNan(n);
        },
        // Строки и объекты: пустая строка = false, иначе true
        .string, .object => return true, // упрощённо
    }
}

/// Преобразовать в число (как в JS: Number(value))
pub fn toNumber(v: JsValue) f64 {
    switch (getTag(v)) {
        .number => return getNumber(v),
        .undefined, .js_nan => return std.math.nan(f64),
        .null, .boolean_false => return 0.0,
        .boolean_true => return 1.0,
        .string => return 0.0, // TODO: парсить строку
        .object => return std.math.nan(f64),
    }
}

// ─────────────────────────────────────────────────────────────
// Отладочный вывод
// ─────────────────────────────────────────────────────────────

pub fn dump(v: JsValue) void {
    switch (getTag(v)) {
        .number => {
            const n = getNumber(v);
            if (std.math.isInf(n)) {
                if (n > 0) std.debug.print("Infinity", .{})
                else std.debug.print("-Infinity", .{});
            } else {
                std.debug.print("{d}", .{n});
            }
        },
        .undefined => std.debug.print("undefined", .{}),
        .null => std.debug.print("null", .{}),
        .boolean_false => std.debug.print("false", .{}),
        .boolean_true => std.debug.print("true", .{}),
        .js_nan => std.debug.print("NaN", .{}),
        .object => std.debug.print("[object Object]@{x}", .{v & PAYLOAD_MASK}),
        .string => std.debug.print("[string]@{x}", .{v & PAYLOAD_MASK}),
    }
}

