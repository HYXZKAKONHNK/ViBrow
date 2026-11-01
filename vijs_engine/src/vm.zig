const std = @import("std");
const js = @import("js_value.zig");
const compiler = @import("compiler.zig");

// ═══════════════════════════════════════════════════════════════
// VMIT — байткод-машина ViBrow
//
// Модель выполнения:
//   • Value stack — стек JsValue (8 байт, NaN-boxing).
//   • Frame stack — стек фреймов; каждый фрейм = массив slots
//     (scope chain). Глобальный скоуп — фрейм №0. Блок { } не
//     создаёт фрейм (слоты блока продолжают счётчик текущего),
//     вызов функции — создаёт.
//   • Closures — (code_ptr, env_ptr). Фреймы, захваченные
//     замыканиями (env/env_base links), переживают RET.
//   • Strings — интернированы (hash → pointer): одинаковый текст
//     даёт одинаковый JsValue ⇒ === за O(1) и дешёвая конкатенация.
//   • Objects — hash map свойств; NEW_OBJ / SET_PROP / GET_PROP.
//
// LOAD/STORE_LOCAL: пара (depth, index), depth считается от вершины
// фрейм-стека — резолв слота за O(1).
// ═══════════════════════════════════════════════════════════════

pub const VmError = error{
    StackOverflow,
    StackUnderflow,
    FrameOverflow,
    CallDepthExceeded,
    InvalidProgram,
    NotCallable,
};

const STACK_SIZE: usize = 4096; // value stack (в значениях)
const MAX_FRAMES: usize = 512; // живых фреймов (включая захваченные)
const MAX_SLOTS: usize = 4096; // суммарно живых слотов (лимит памяти вкладки)
const MAX_CALL_STACK: usize = 128; // глубина рекурсии CALL→RET
const MAX_VALUE_BYTES: usize = 32 * 1024; // строки+объекты на программу

/// Интернированная строка: один экземпляр на текст (hash → pointer).
/// Поле bytes хранится как заголовок js.StrHeader — JsValue строки
/// указывает прямо на это поле (len+ptr), без额外 аллокаций.
pub const Str = struct {
    header: js.StrHeader,

    pub fn bytes(self: *const Str) []const u8 {
        return self.header.ptr[0..self.header.len];
    }
};

/// Хеш-мапа свойств JS-объекта.
pub const ObjMap = std.StringHashMap(js.JsValue);

/// Closure = (code_ptr, env_ptr) — ровно как просили.
pub const Closure = struct {
    code: []const compiler.Instruction, // указатель на байткод прототипа
    env: ?*Frame, // фрейм места создания (лексическое окружение)
    env_base: ?*Frame, // base-фрейм внешней функции (продолжает цепочку выше env)
    arity: u16,
    local_count: u16, // размер фрейма при вызове
    name: []const u8,
};

/// Фрейм = scope: массив slots + link к closure-окружению.
pub const Frame = struct {
    slots: []js.JsValue,
    env: ?*Frame, // цепочка скоупов: фрейм, непосредственно окружающий этот
    parent: ?*Frame, // предыдущий фрейм фрейм-стека VM
    live: bool, // false — фрейм снят со стека и доступен только из closures
};

/// Возвратный адрес вызова (CALL → RET).
const ReturnAddr = struct {
    ip: usize, // куда продолжить в коде вызывающего
    code: []const compiler.Instruction,
};

pub const VM = struct {
    alloc: std.mem.Allocator,
    image: *const compiler.ProgramImage,

    // ── value stack ──
    stack: []js.JsValue,
    sp: usize = 0,

    // ── frame stack ──
    frames: [MAX_FRAMES]?*Frame = [_]?*Frame{null} ** MAX_FRAMES,
    fp: usize = 0,
    total_slots: usize = 0,

    // ── call stack ──
    calls: [MAX_CALL_STACK]ReturnAddr = [_]ReturnAddr{.{ .ip = 0, .code = &[_]compiler.Instruction{} }} ** MAX_CALL_STACK,
    cp: usize = 0,

    // ── heap значений ──
    strings: std.StringHashMap(*Str), // intern table: text → pointer
    str_store: std.ArrayList(*Str),
    objs: std.ArrayList(*ObjMap),
    closures: std.ArrayList(*Closure),
    frames_owned: std.ArrayList(*Frame),
    globals: std.StringHashMap(js.JsValue), // глобальные имена → значения
    value_bytes: usize = 0,

    pub fn init(alloc: std.mem.Allocator, image: *const compiler.ProgramImage) !VM {
        var vm = VM{
            .alloc = alloc,
            .image = image,
            .stack = try alloc.alloc(js.JsValue, STACK_SIZE),
            .strings = std.StringHashMap(*Str).init(alloc),
            .str_store = std.ArrayList(*Str).init(alloc),
            .objs = std.ArrayList(*ObjMap).init(alloc),
            .closures = std.ArrayList(*Closure).init(alloc),
            .frames_owned = std.ArrayList(*Frame).init(alloc),
            .globals = std.StringHashMap(js.JsValue).init(alloc),
        };
        errdefer vm.freeHeap();
        // Пред-интернинг таблицы строк образа: LOAD_STR всегда отдаёт
        // готовый pointer без аллокаций в рантайме.
        for (image.strings) |text| {
            _ = try vm.intern(text);
        }
        return vm;
    }

    pub fn deinit(self: *VM) void {
        self.alloc.free(self.stack);
        self.freeHeap();
    }

    fn freeHeap(self: *VM) void {
        self.globals.deinit();
        for (self.frames_owned.items) |f| self.freeFrame(f);
        self.frames_owned.deinit();
        for (self.objs.items) |o| {
            o.deinit();
            self.alloc.destroy(o);
        }
        self.objs.deinit();
        for (self.closures.items) |c| self.alloc.destroy(c);
        self.closures.deinit();
        self.strings.deinit();
        for (self.str_store.items) |s| {
            self.alloc.free(s.header.ptr[0..s.header.len]);
            self.alloc.destroy(s);
        }
        self.str_store.deinit();
    }

    fn freeFrame(self: *VM, f: *Frame) void {
        self.total_slots -= f.slots.len;
        self.alloc.free(f.slots);
        self.alloc.destroy(f);
    }

    inline fn chargeBytes(self: *VM, n: usize) VmError!void {
        if (self.value_bytes + n > MAX_VALUE_BYTES) return error.FrameOverflow;
        self.value_bytes += n;
    }

    // ───────── value stack helpers ─────────

    inline fn push(self: *VM, v: js.JsValue) VmError!void {
        if (self.sp >= STACK_SIZE) return error.StackOverflow;
        self.stack[self.sp] = v;
        self.sp += 1;
    }

    inline fn pop(self: *VM) VmError!js.JsValue {
        if (self.sp == 0) return error.StackUnderflow;
        self.sp -= 1;
        return self.stack[self.sp];
    }

    inline fn peek(self: *VM) VmError!js.JsValue {
        if (self.sp == 0) return error.StackUnderflow;
        return self.stack[self.sp - 1];
    }

    // ───────── frames (scope chain) ─────────

    fn curFrame(self: *VM) VmError!*Frame {
        if (self.fp == 0) return error.InvalidProgram;
        return self.frames[self.fp - 1].?;
    }

    /// Создать фрейм из live-пула (переиспользование после RET).
    fn makeFrame(self: *VM, n: usize, env: ?*Frame) VmError!*Frame {
        if (n == 0) return error.InvalidProgram;
        if (self.total_slots + n > MAX_SLOTS) return error.FrameOverflow;
        // ищем свободный фрейм достаточного размера
        for (self.frames_owned.items) |f| {
            if (!f.live and f.slots.len >= n) {
                @memset(f.slots[0..n], js.UNDEFINED);
                f.slots = f.slots[0..n];
                f.env = env;
                f.live = true;
                self.total_slots += n;
                return f;
            }
        }
        if (self.frames_owned.items.len >= MAX_FRAMES) return error.FrameOverflow;
        const f = try self.alloc.create(Frame);
        errdefer self.alloc.destroy(f);
        const backing = try self.alloc.alloc(js.JsValue, n);
        errdefer self.alloc.free(backing);
        @memset(backing, js.UNDEFINED);
        f.* = .{ .slots = backing, .env = env, .parent = null, .live = true };
        self.total_slots += n;
        try self.frames_owned.append(f);
        return f;
    }

    fn pushFrame(self: *VM, f: *Frame) VmError!void {
        if (self.fp >= MAX_FRAMES) return error.FrameOverflow;
        f.parent = if (self.fp > 0) self.frames[self.fp - 1] else null;
        // Цепочка скоупов: обычный фрейм (не closure-call) окружён текущим.
        if (f.env == null) f.env = if (self.fp > 0) self.frames[self.fp - 1] else null;
        self.frames[self.fp] = f;
        self.fp += 1;
    }

    fn popFrame(self: *VM) VmError!*Frame {
        if (self.fp == 0) return error.InvalidProgram;
        self.fp -= 1;
        const f = self.frames[self.fp].?;
        self.frames[self.fp] = null;
        f.parent = null;
        f.live = false; // снят со стека: доступен только через closures
        return f;
    }

    /// Разрешить (depth, index): идём по цепочке скоупов env от
    /// вершины фрейм-стека. depth=0 — текущий фрейм (его блок/функция),
    /// глубже — окружающие фреймы (в т.ч. уже снятые со стека, но
    /// живущие благодаря links). Резолв O(depth), без аллокаций.
    fn resolveSlot(self: *VM, depth: u16, index: u16) VmError!*js.JsValue {
        if (self.fp == 0) return error.InvalidProgram;
        var cur: ?*Frame = self.frames[self.fp - 1];
        var d: usize = 0;
        while (cur) |f| : (d += 1) {
            if (d == depth) {
                if (index >= f.slots.len) return error.InvalidProgram;
                return &f.slots[index];
            }
            cur = f.env;
        }
        return error.InvalidProgram;
    }

    /// Имя глобальной переменной по индексу таблицы строк образа.
    fn globalName(self: *VM, idx: usize) VmError![]const u8 {
        if (idx >= self.image.strings.len) return error.InvalidProgram;
        return self.image.strings[idx];
    }

    // ───────── strings (interned: hash → pointer) ─────────

    fn intern(self: *VM, text: []const u8) VmError!*Str {
        if (self.strings.get(text)) |s| return s;
        try self.chargeBytes(text.len);
        const s = try self.alloc.create(Str);
        errdefer self.alloc.destroy(s);
        const duped = try self.alloc.dupe(u8, text);
        errdefer self.alloc.free(duped);
        s.header = .{ .len = duped.len, .ptr = duped.ptr };
        try self.strings.put(duped, s);
        try self.str_store.append(s);
        return s;
    }

    fn strValueByIdx(self: *VM, idx: usize) VmError!js.JsValue {
        if (idx >= self.image.strings.len) return error.InvalidProgram;
        const s = try self.intern(self.image.strings[idx]);
        return js.fromString(s);
    }

    fn strBytes(v: js.JsValue) []const u8 {
        return js.strBytes(v);
    }

    /// Конкатенация a ++ b с интернингом результата (детерминированные
    /// строки не плодят дублей в heap).
    fn concat(self: *VM, a: []const u8, b: []const u8) VmError!js.JsValue {
        const buf = try self.alloc.alloc(u8, a.len + b.len);
        defer self.alloc.free(buf);
        @memcpy(buf[0..a.len], a);
        @memcpy(buf[a.len..], b);
        const s = try self.intern(buf);
        return js.fromString(s);
    }

    // ───────── objects (hash map) ─────────

    fn newObject(self: *VM) VmError!js.JsValue {
        try self.chargeBytes(128); // грубая стоимость пустой мапы
        const map = try self.alloc.create(ObjMap);
        errdefer self.alloc.destroy(map);
        map.* = ObjMap.init(self.alloc);
        try self.objs.append(map);
        return js.fromObject(map);
    }

    fn objMap(v: js.JsValue) *ObjMap {
        return @ptrCast(@alignCast(js.getObjectPtr(v)));
    }

    // ───────── closures ─────────

    fn makeClosure(self: *VM, proto_idx: usize) VmError!js.JsValue {
        if (proto_idx >= self.image.funcs.len) return error.InvalidProgram;
        const proto = &self.image.funcs[proto_idx];
        const c = try self.alloc.create(Closure);
        errdefer self.alloc.destroy(c);
        // env — фрейм места создания; outer — base-фрейм внешней функции
        // (нужен, когда внутри возвращённого замыкания резолвятся free
        // variables глубже env: outer даёт продолжение цепочки вверх).
        const cur = self.curFrame() catch null;
        c.* = .{
            .code = proto.code, // code_ptr
            .env = cur, // env_ptr — фрейм места создания
            // Если замыкание создано внутри ВЫЗОВА функции (cur — её
            // фрейм), то cur был помещён в стек с env = лексическое
            // окружение самой функции. Цепочка от new-func фрейма:
            //   nf.env = cur(outer frame)... уже корректна через pushFrame.
            // env_base нужен для случаев, когда cur снят со стека позже:
            // сохраняем его link на окружение, чтобы цепочка не рвалась.
            .env_base = if (cur) |fr| fr.env else null,
            .arity = proto.arity,
            .local_count = proto.local_count,
            .name = proto.name,
        };
        try self.closures.append(c);
        return js.fromClosure(c);
    }

    // ───────── runtime conversions ─────────

    fn toStrRuntime(self: *VM, v: js.JsValue) VmError![]const u8 {
        switch (js.getTag(v)) {
            .string => return strBytes(v),
            .number => {
                var buf: [64]u8 = undefined;
                const n = js.getNumber(v);
                const s = std.fmt.bufPrint(&buf, "{d}", .{n}) catch return "";
                const st = try self.intern(s);
                return st.bytes();
            },
            .undefined => return (try self.intern("undefined")).bytes(),
            .null => return (try self.intern("null")).bytes(),
            .boolean_true => return (try self.intern("true")).bytes(),
            .boolean_false => return (try self.intern("false")).bytes(),
            .js_nan => return (try self.intern("NaN")).bytes(),
            .closure => return (try self.intern("function")).bytes(),
            .object => return (try self.intern("[object Object]")).bytes(),
        }
    }

    fn toNumberRuntime(self: *VM, v: js.JsValue) f64 {
        switch (js.getTag(v)) {
            .number => return js.getNumber(v),
            .undefined, .js_nan, .object, .closure => return std.math.nan(f64),
            .null, .boolean_false => return 0.0,
            .boolean_true => return 1.0,
            .string => {
                const t = std.mem.trim(u8, strBytes(v), " \t\r\n");
                if (t.len == 0) return 0.0;
                return std.fmt.parseFloat(f64, t) catch std.math.nan(f64);
            },
        }
    }

    /// Абстрактное равенство (==). Для интернов сравнение указателей
    /// (a == b) уже корректно и O(1).
    fn abstractEq(self: *VM, a: js.JsValue, b: js.JsValue) VmError!bool {
        if (a == b) return true; // same-value: числа, строки-интерны, true/false…
        const ta = js.getTag(a);
        const tb = js.getTag(b);
        if (ta == .undefined or ta == .null or tb == .undefined or tb == .null) {
            // null == undefined, но больше ни с чем
            return (ta == .undefined or ta == .null) and (tb == .undefined or tb == .null);
        }
        const a_numish = ta == .number or ta == .boolean_true or ta == .boolean_false;
        const b_numish = tb == .number or tb == .boolean_true or tb == .boolean_false;
        if ((a_numish and tb == .string) or (ta == .string and b_numish)) {
            return self.toNumberRuntime(a) == self.toNumberRuntime(b);
        }
        return false;
    }

    fn strictEq(_: *VM, a: js.JsValue, b: js.JsValue) bool {
        return a == b; // NaN-boxing + интернинг: побитовое равенство == SameValue
    }

    fn lessThan(self: *VM, a: js.JsValue, b: js.JsValue) VmError!bool {
        if (js.isString(a) and js.isString(b)) {
            return std.mem.order(u8, strBytes(a), strBytes(b)) == .lt;
        }
        const na = self.toNumberRuntime(a);
        const nb = self.toNumberRuntime(b);
        if (std.math.isNan(na) or std.math.isNan(nb)) return false;
        return na < nb;
    }

    // ───────── основной цикл ─────────

    /// Ссылается ли какое-нибудь closure на фрейм (env или outer)?
    fn isReferenced(self: *VM, f: *Frame) bool {
        for (self.closures.items) |c| {
            if (c.env == f or c.env_base == f) return true;
        }
        return false;
    }

    /// Выполнить main_code программы. Результат — значение последнего
    /// expression statement (как console eval), либо undefined.
    pub fn runMain(self: *VM) VmError!js.JsValue {
        const gframe = try self.makeFrame(@max(self.image.main_locals, 1), null);
        try self.pushFrame(gframe);
        var last: js.JsValue = js.UNDEFINED;
        try self.runCode(self.image.main_code, &last);
        if (self.fp != 0) return error.InvalidProgram;
        return last;
    }

    fn runCode(self: *VM, code0: []const compiler.Instruction, last: *js.JsValue) VmError!void {
        var code = code0;
        var ip: usize = 0;

        while (true) {
            if (ip >= code.len) {
                // Дошли до конца тела без явного RET.
                if (self.cp == 0) break; // это main — завершаем программу
                try self.returnFromCall(js.UNDEFINED, &code, &ip);
                continue;
            }
            const inst = code[ip];
            ip += 1;

            switch (inst.opcode) {
                .LOAD_CONST => try self.push(js.fromNumber(inst.num())),
                .LOAD_STR => try self.push(try self.strValueByIdx(inst.idx())),
                .LOAD_TRUE => try self.push(js.TRUE),
                .LOAD_FALSE => try self.push(js.FALSE),
                .LOAD_NULL => try self.push(js.NULL),
                .LOAD_UNDEF => try self.push(js.UNDEFINED),
                .POP => last.* = try self.pop(), // statement-выражение: его результат — «последнее значение»
                .DUP => try self.push(try self.peek()),

                .ADD => {
                    const b = try self.pop();
                    const a = try self.pop();
                    if (js.isString(a) or js.isString(b)) {
                        try self.push(try self.concat(try self.toStrRuntime(a), try self.toStrRuntime(b)));
                    } else {
                        try self.push(js.fromNumber(self.toNumberRuntime(a) + self.toNumberRuntime(b)));
                    }
                },
                .SUB => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromNumber(self.toNumberRuntime(a) - self.toNumberRuntime(b)));
                },
                .MUL => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromNumber(self.toNumberRuntime(a) * self.toNumberRuntime(b)));
                },
                .DIV => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromNumber(self.toNumberRuntime(a) / self.toNumberRuntime(b)));
                },
                .MOD => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromNumber(@rem(self.toNumberRuntime(a), self.toNumberRuntime(b))));
                },
                .POW => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromNumber(std.math.pow(f64, self.toNumberRuntime(a), self.toNumberRuntime(b))));
                },
                .NEG => {
                    const a = try self.pop();
                    try self.push(js.fromNumber(-self.toNumberRuntime(a)));
                },
                .NOT => {
                    const a = try self.pop();
                    try self.push(js.fromBool(!js.toBoolean(a)));
                },

                .EQ => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromBool(try self.abstractEq(a, b)));
                },
                .STRICT_EQ => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromBool(self.strictEq(a, b)));
                },
                .NEQ => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromBool(!(try self.abstractEq(a, b))));
                },
                .STRICT_NEQ => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromBool(!self.strictEq(a, b)));
                },
                .LT => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromBool(try self.lessThan(a, b)));
                },
                .LE => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromBool(!(try self.lessThan(b, a))));
                },
                .GT => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromBool(try self.lessThan(b, a)));
                },
                .GE => {
                    const b = try self.pop();
                    const a = try self.pop();
                    try self.push(js.fromBool(!(try self.lessThan(a, b))));
                },

                .JMP => ip = inst.idx(),
                .JMP_IF_FALSE => {
                    const c = try self.pop();
                    if (!js.toBoolean(c)) ip = inst.idx();
                },
                .JMP_IF_TRUE => {
                    const c = try self.pop();
                    if (js.toBoolean(c)) ip = inst.idx();
                },
                .TEST_AND_KEEP => {
                    // a && b: falsy-вершина остаётся на стеке и является результатом
                    if (!js.toBoolean(try self.peek())) ip = inst.idx();
                },
                .TEST_OR_KEEP => {
                    // a || b: truthy-вершина остаётся
                    if (js.toBoolean(try self.peek())) ip = inst.idx();
                },

                .LOAD_LOCAL => {
                    const slot = try self.resolveSlot(inst.depth(), inst.slot());
                    try self.push(slot.*);
                },
                .STORE_LOCAL => {
                    const v = try self.peek();
                    const slot = try self.resolveSlot(inst.depth(), inst.slot());
                    slot.* = v;
                },
                .LOAD_GLOBAL => {
                    const name = try self.globalName(inst.idx());
                    if (self.globals.get(name)) |v| {
                        try self.push(v);
                    } else {
                        try self.push(js.UNDEFINED);
                    }
                },
                .STORE_GLOBAL => {
                    const v = try self.peek();
                    const name = try self.globalName(inst.idx());
                    try self.globals.put(name, v);
                },
                .DECLARE_LOCAL => {}, // слот выделен при создании фрейма (= undefined)

                .PUSH_FUNC => try self.push(try self.makeClosure(inst.idx())),

                .CALL => {
                    const argc = inst.idx();
                    if (self.sp < argc + 1) return error.StackUnderflow;
                    const callee = self.stack[self.sp - argc - 1];
                    if (js.getTag(callee) != .closure) return error.NotCallable;
                    const c: *Closure = @ptrCast(@alignCast(js.getClosurePtr(callee)));
                    if (c.env == null) return error.NotCallable;
                    if (self.cp >= MAX_CALL_STACK) return error.CallDepthExceeded;

                    const n: usize = @max(@as(usize, c.arity), @as(usize, c.local_count));
                    // Цепочка скоупов вызываемой функции сшивается из
                    // closure: nf -> c.env -> ... -> c.env_base -> ...
                    const nf = try self.makeFrame(@max(n, 1), c.env);
                    for (0..@min(argc, @as(usize, c.arity))) |k| {
                        nf.slots[k] = self.stack[self.sp - argc + k];
                    }
                    self.sp -= argc + 1; // снять callee + args
                    try self.pushFrame(nf);
                    self.calls[self.cp] = .{ .ip = ip, .code = code };
                    self.cp += 1;
                    code = c.code;
                    ip = 0;
                },

                .RET => {
                    if (self.cp == 0) return error.InvalidProgram; // ret вне вызова
                    const rv = try self.pop();
                    try self.returnFromCall(rv, &code, &ip);
                },
                .RET_UNDEF => {
                    if (self.cp == 0) break; // конец main
                    try self.returnFromCall(js.UNDEFINED, &code, &ip);
                },

                .NEW_OBJ => try self.push(try self.newObject()),
                .SET_PROP => {
                    const value = try self.pop();
                    const keyv = try self.pop();
                    const obj = try self.peek(); // obj остаётся на стеке
                    if (!js.isObject(obj) or !js.isString(keyv)) return error.InvalidProgram;
                    try self.objMap(obj).put(strBytes(keyv), value);
                },
                .GET_PROP => {
                    const keyv = try self.pop();
                    const obj = try self.pop();
                    if (!js.isString(keyv)) {
                        try self.push(js.UNDEFINED);
                        continue;
                    }
                    const key = strBytes(keyv);
                    switch (js.getTag(obj)) {
                        .object => {
                            if (self.objMap(obj).get(key)) |v| {
                                try self.push(v);
                            } else {
                                try self.push(js.UNDEFINED);
                            }
                        },
                        .string => {
                            // Псевдо-свойства примитивов: "abc".length
                            if (std.mem.eql(u8, key, "length")) {
                                try self.push(js.fromNumber(@floatFromInt(strBytes(obj).len)));
                            } else {
                                try self.push(js.UNDEFINED);
                            }
                        },
                        else => try self.push(js.UNDEFINED),
                    }
                },
            }
        }
    }

    /// Общий выход из функции: снять фрейм (если на него нет ссылок — в пул),
    /// положить возвращаемое значение, восстановить код/ip вызывающего.
    fn returnFromCall(self: *VM, rv: js.JsValue, code: *[]const compiler.Instruction, ip: *usize) VmError!void {
        const ra = self.calls[self.cp - 1];
        self.cp -= 1;
        const done = try self.popFrame();
        // Фрейм, на который ссылается хотя бы одно closure (env/env_base),
        // НЕ возвращается в пул — иначе замыкание повиснет на чужих данных.
        if (!self.isReferenced(done)) {
            self.total_slots -= done.slots.len;
            // фрейм остаётся в frames_owned для переиспользования (live pool)
        }
        try self.push(rv);
        code.* = ra.code;
        ip.* = ra.ip;
    }
};

// ═══════════════════════════════════════════════════════════════
// Старый API (совместимость): execute(bytecode) — только арифметика
// ═══════════════════════════════════════════════════════════════

pub fn execute(allocator: std.mem.Allocator, bytecode: []compiler.Instruction) !js.JsValue {
    var dummy_strings = std.ArrayList([]const u8).init(allocator);
    defer dummy_strings.deinit();
    var image = compiler.ProgramImage{
        .main_code = bytecode,
        .main_locals = 0,
        .funcs = &[_]compiler.FunctionProto{},
        .strings = dummy_strings.items,
    };
    var vm = try VM.init(allocator, &image);
    defer vm.deinit();
    return vm.runMain();
}
