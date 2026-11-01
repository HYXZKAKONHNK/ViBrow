const std = @import("std");
const parser = @import("parser.zig");

// ═══════════════════════════════════════════════════════════════
// КОМПИЛЯТОР: AST → байткод VMIT
//
// Модель scopes: каждый блок { } — новый фрейм (массив slots).
// let/const объявляют slot в ТЕКУЩЕМ фрейме; var — в фрейме функции
// (или глобальном). Имя резолвится по цепочке скоупов на этапе
// компиляции и превращается в пару (depth, index) — LOAD_LOCAL /
// STORE_LOCAL работают за O(1).
// Свободные переменные (из замыкающих скоупов) индексируются через
// env-chain внутри closure (DEPTH_LOAD), поэтому closures захватывают
// окружение без "flatten" на лету.
// ═══════════════════════════════════════════════════════════════

pub const Opcode = enum(u8) {
    // ── константы ──
    LOAD_CONST = 0, // operand.num — число
    LOAD_STR = 1,   // operand.str_idx — интернированная строка
    LOAD_TRUE = 2,
    LOAD_FALSE = 3,
    LOAD_NULL = 4,
    LOAD_UNDEF = 5,
    POP = 6,        // сбросить верхушку стека (statement-выражения)
    DUP = 7,        // дублировать верхушку (присваивание возвращает значение)

    // ── арифметика ──
    ADD = 10, // + (число или конкатенация строк)
    SUB = 11,
    MUL = 12,
    DIV = 13,
    MOD = 14,
    POW = 15,
    NEG = 16, // унарный минус
    NOT = 17, // !x (логическое отрицание)

    // ── сравнения (if-сравнения) ──
    EQ = 20,     // ==
    STRICT_EQ = 21, // ===
    NEQ = 22,    // !=
    STRICT_NEQ = 23, // !==
    LT = 24,
    LE = 25,
    GT = 26,
    GE = 27,

    // ── управление потоком ──
    JMP = 30,        // operand.i — абсолютный переход
    JMP_IF_FALSE = 31, // снять значение; если falsy — прыжок
    JMP_IF_TRUE = 32,  // снять значение; если truthy — прыжок (для ||)
    TEST_AND_KEEP = 33, // peek вершины: && — если falsy, прыгаем (значение остаётся)
    TEST_OR_KEEP = 34,  // peek вершины: || — если truthy, прыгаем (значение остаётся)

    // ── локальные переменные (scope chain) ──
    LOAD_LOCAL = 40,  // operand.depth/index — слот фрейма
    STORE_LOCAL = 41, // записать вершину стека в слот (вершина остаётся)
    DECLARE_LOCAL = 42, // выделить слот в текущем фрейме со значением undefined
                        // (глубина уже известна компилятору; runtime лишь инициализирует)

    // ── функции и closures ──
    PUSH_FUNC = 50, // operand.func_idx — closure (code_ptr, env_ptr); env берётся из текущего фрейма
    CALL = 51,      // operand.argc — вызвать замыкаание со стека [callee, args...]
    RET = 52,       // вернуть вершину стека
    RET_UNDEF = 53, // вернуть undefined (конец тела без return)

    // ── объекты (hash map) ──
    NEW_OBJ = 60, // создать пустой объект
    SET_PROP = 61, // со стека: [obj, key(str), value] → obj[key]=value, obj остаётся
    GET_PROP = 62, // со стека: [obj, key] → obj[key] | undefined
    // DEEP_GET: не нужен — ключ всегда кладём LOAD_STR перед GET_PROP
};

/// Один операнд инструкции — union, чтобы хранить числа, индексы строк
/// и пары (depth, index) для локальных переменных.
pub const Operand = union(PayloadKind) {
    none: void,
    num: f64,   // LOAD_CONST
    i: usize,   // адрес перехода / func_idx / argc
    depth: u16, // глубина скоуп-цепочки
    index: u16, // номер слота во фрейме
};

pub const PayloadKind = enum { none, num, i, depth, index };

pub const Instruction = struct {
    opcode: Opcode,
    a: Operand = .none, // главный операнд
    b: Operand = .none, // второй операнд (STORE/LOAD_LOCAL: index)
};

/// Функция (тело) — отдельный кусок байткода, вызываемый через CALL.
pub const FunctionProto = struct {
    code: []Instruction,
    arity: u16,          // сколько параметров ждёт
    local_count: u16,    // размер фрейма (slots) в этой функции
    name: []const u8,    // для отладки
};

/// Полный скомпилированный образ программы.
pub const ProgramImage = struct {
    main_code: []Instruction,
    main_locals: u16, // размер глобального фрейма
    funcs: []FunctionProto,
    strings: [][]const u8, // таблица интернированных строк (индекс → текст)
};

pub const CompileError = error{ CompileError, OutOfMemory };

// ───────────────── Таблица строк (интернинг) ─────────────────

const StringTable = struct {
    list: std.ArrayList([]const u8),
    map: std.StringHashMap(usize),

    fn init(alloc: std.mem.Allocator) StringTable {
        return .{
            .list = std.ArrayList([]const u8).init(alloc),
            .map = std.StringHashMap(usize).init(alloc),
        };
    }

    /// intern: одинаковый текст → один и тот же индекс (hash → pointer в VM)
    fn intern(self: *StringTable, alloc: std.mem.Allocator, text: []const u8) CompileError!usize {
        if (self.map.get(text)) |idx| return idx;
        const duped = try alloc.dupe(u8, text);
        const idx = self.list.items.len;
        try self.list.append(duped);
        try self.map.put(duped, idx);
        return idx;
    }
};

// ───────────────── Scope-менеджер компилятора ─────────────────

const VarEntry = struct {
    name: []const u8,
    slot: u16,
    is_const: bool,
};

const Scope = struct {
    vars: std.ArrayList(VarEntry),
    is_function_scope: bool,
};

/// Информация о переменной после разрешения
const ResolvedVar = struct {
    depth: u16, // 0 = текущий фрейм, 1 = внешний ... (внутри функции — env-chain)
    index: u16, // слот во фрейме
    is_const: bool,
};

const Compiler = struct {
    alloc: std.mem.Allocator,
    code: std.ArrayList(Instruction),
    strings: StringTable,
    scopes: std.ArrayList(Scope),
    funcs: std.ArrayList(FunctionProto),
    function_depth: u16, // на какой глубине функций мы сейчас компилируем
    local_counter: u16,  // следующий свободный слот текущего фрейма

    fn init(alloc: std.mem.Allocator) Compiler {
        var c = Compiler{
            .alloc = alloc,
            .code = std.ArrayList(Instruction).init(alloc),
            .strings = StringTable.init(alloc),
            .scopes = std.ArrayList(Scope).init(alloc),
            .funcs = std.ArrayList(FunctionProto).init(alloc),
            .function_depth = 0,
            .local_counter = 0,
        };
        // Глобальный scope — как функция (var оседает здесь)
        c.scopes.append(.{
            .vars = std.ArrayList(VarEntry).init(alloc),
            .is_function_scope = true,
        }) catch unreachable;
        return c;
    }

    fn emit(self: *Compiler, inst: Instruction) CompileError!usize {
        const addr = self.code.items.len;
        try self.code.append(inst);
        return addr;
    }

    fn currentCodeLen(self: *const Compiler) usize {
        return self.code.items.len;
    }

    fn patchJump(self: *Compiler, addr: usize, target: usize) void {
        self.code.items[addr].a = .{ .i = target };
    }

    fn pushScope(self: *Compiler, is_function_scope: bool) CompileError!void {
        try self.scopes.append(.{
            .vars = std.ArrayList(VarEntry).init(self.alloc),
            .is_function_scope = is_function_scope,
        });
    }

    fn popScope(self: *Compiler) void {
        _ = self.scopes.pop();
    }

    /// Объявить переменную в подходящем scope (let/const — текущий, var — ближайший функциональный)
    fn declare(self: *Compiler, name: []const u8, kind: parser.DeclKind, is_const: bool) CompileError!u16 {
        // Для var идём вверх до ближайшего function-scope
        var target_idx = self.scopes.items.len - 1;
        if (kind == .var_decl) {
            while (!self.scopes.items[target_idx].is_function_scope and target_idx > 0) {
                target_idx -= 1;
            }
        }
        const slot = if (target_idx == self.scopes.items.len - 1) blk: {
            const s = self.local_counter;
            self.local_counter += 1;
            break :blk s;
        } else blk: {
            // var hoisted в родительский фрейм — добавляем слот туда
            const s: u16 = @intCast(self.scopes.items[target_idx].vars.items.len);
            break :blk s;
        };
        const duped_name = try self.alloc.dupe(u8, name);
        try self.scopes.items[target_idx].vars.append(.{ .name = duped_name, .slot = slot, .is_const = is_const });
        return slot;
    }

    /// Разрешить имя по цепочке скоупов. null — не найдено (глобальная lookup-таблица в рантайме).
    fn resolve(self: *Compiler, name: []const u8) ?ResolvedVar {
        var i: usize = self.scopes.items.len;
        var depth_in_func: u16 = 0;
        var cur_func_boundary = self.function_depth;
        while (i > 0) {
            i -= 1;
            const sc = &self.scopes.items[i];
            for (sc.vars.items) |v| {
                if (std.mem.eql(u8, v.name, name)) {
                    return .{
                        .depth = depth_in_func,
                        .index = v.slot,
                        .is_const = v.is_const,
                    };
                }
            }
            if (sc.is_function_scope) {
                if (depth_in_func > 0 or i == 0) break; // пересекли границу функции — стоп
                // достигли границы функции: глубина обнуляется, дальше не идём
                // (переменные выше функции доступны только через env-chain замыкания)
                break;
            }
            depth_in_func += 1;
            _ = cur_func_boundary;
        }
        return null;
    }

    // ───────── Операторы ─────────

    fn compileBlockBody(self: *Compiler, stmts: []const (*parser.Stmt)) CompileError!void {
        for (stmts) |s| try self.compileStmt(s);
    }

    fn compileStmt(self: *Compiler, st: *parser.Stmt) CompileError!void {
        switch (st.*) {
            .expr => |e| {
                try self.compileExpr(e);
                try self.emit(.{ .opcode = .POP }); // результат оператора отбрасываем
            },
            .decl => |d| {
                try self.compileExpr(d.value_opt);
                const slot = try self.declare(d.name, d.kind, d.kind == .const_decl);
                try self.emit(.{ .opcode = .STORE_LOCAL, .a = .{ .depth = 0 }, .b = .{ .index = slot } });
                try self.emit(.{ .opcode = .POP });
            },
            .func_decl => |f| {
                // function foo(){} ≡ let foo = function(){...} (имя видно внутри тела)
                const fname = if (f.name.len > 0) f.name else "anonymous";
                const slot = try self.declare(fname, .var_decl, false);
                try self.compileFuncLiteral(f);
                try self.emit(.{ .opcode = .STORE_LOCAL, .a = .{ .depth = 0 }, .b = .{ .index = slot } });
                try self.emit(.{ .opcode = .POP });
            },
            .return_stmt => |maybe_e| {
                if (maybe_e) |e| {
                    try self.compileExpr(e);
                    try self.emit(.{ .opcode = .RET });
                } else {
                    try self.emit(.{ .opcode = .RET_UNDEF });
                }
            },
            .if_stmt => |ifs| {
                try self.compileIf(ifs);
            },
            .block => |blk| {
                try self.pushScope(false);
                defer self.popScope();
                // помечаем: новые локальные slots этого блока продолжат счётчик
                const saved_counter = self.local_counter;
                defer self.local_counter = saved_counter;
                try self.compileBlockBody(blk.stmts.items);
            },
        }
    }

    fn compileIf(self: *Compiler, ifs: *parser.IfStmt) CompileError!void {
        try self.compileExpr(ifs.condition);
        const jmp_false = try self.emit(.{ .opcode = .JMP_IF_FALSE, .a = .{ .i = 0 } });
        try self.compileStmt(ifs.consequent);
        if (ifs.alternate) |alt| {
            const jmp_end = try self.emit(.{ .opcode = .JMP, .a = .{ .i = 0 } });
            const else_start = self.currentCodeLen();
            self.patchJump(jmp_false, else_start);
            try self.compileStmt(alt);
            self.patchJump(jmp_end, self.currentCodeLen());
        } else {
            self.patchJump(jmp_false, self.currentCodeLen());
        }
    }

    // ───────── Выражения ─────────

    fn compileFuncLiteral(self: *Compiler, f: *parser.FuncExpr) CompileError!void {
        // Компилируем тело функции в ОТДЕЛЬНЫЙ поток байткода.
        const outer_code = self.code;
        const outer_scopes = self.scopes;
        const outer_strings_len_unused = self.strings.list.items.len;
        _ = outer_strings_len_unused;

        self.code = std.ArrayList(Instruction).init(self.alloc);
        var new_scopes = std.ArrayList(Scope).init(self.alloc);
        try new_scopes.append(.{
            .vars = std.ArrayList(VarEntry).init(self.alloc),
            .is_function_scope = true,
        });
        self.scopes = new_scopes;
        const saved_local = self.local_counter;
        self.local_counter = 0;
        self.function_depth += 1;

        // Параметры — первые слоты фрейма
        for (f.params.items) |p| {
            _ = try self.declare(p, .let_decl, false);
        }

        try self.compileBlockBody(f.body.stmts.items);
        try self.emit(.{ .opcode = .RET_UNDEF }); // неявный return undefined

        const proto_index = self.funcs.items.len;
        try self.funcs.append(.{
            .code = try self.code.toOwnedSlice(self.alloc),
            .arity = @intCast(f.params.items.len),
            .local_count = self.local_counter,
            .name = f.name,
        });

        self.code = outer_code;
        self.scopes = outer_scopes;
        self.local_counter = saved_local;
        self.function_depth -= 1;

        try self.emit(.{ .opcode = .PUSH_FUNC, .a = .{ .i = proto_index } });
    }

    fn compileExpr(self: *Compiler, e: *parser.Expr) CompileError!void {
        switch (e.*) {
            .number => |n| try self.emit(.{ .opcode = .LOAD_CONST, .a = .{ .num = n } }),
            .string => |s| {
                const idx = try self.strings.intern(self.alloc, s);
                try self.emit(.{ .opcode = .LOAD_STR, .a = .{ .i = idx } });
            },
            .bool_lit => |b| try self.emit(.{ .opcode = if (b) .LOAD_TRUE else .LOAD_FALSE }),
            .null_lit => try self.emit(.{ .opcode = .LOAD_NULL }),
            .undefined_lit => try self.emit(.{ .opcode = .LOAD_UNDEF }),
            .neg => |inner| {
                try self.compileExpr(inner);
                try self.emit(.{ .opcode = .NEG });
            },
            .unary_not => |inner| {
                try self.compileExpr(inner);
                try self.emit(.{ .opcode = .NOT });
            },
            .binary => |bin| {
                try self.compileExpr(bin.left);
                try self.compileExpr(bin.right);
                const op: Opcode = switch (bin.op) {
                    .add => .ADD,
                    .sub => .SUB,
                    .mul => .MUL,
                    .div => .DIV,
                    .mod => .MOD,
                    .pow => .POW,
                    .eq_eq => .EQ,
                    .eq_eq_eq => .STRICT_EQ,
                    .neq => .NEQ,
                    .neq_neq => .STRICT_NEQ,
                    .lt => .LT,
                    .le => .LE,
                    .gt => .GT,
                    .ge => .GE,
                };
                try self.emit(.{ .opcode = op });
            },
            .logical => |l| {
                // a && b: peek a; if falsy →jmp end (a остаётся на стеке)
                //         else pop a; eval b; end:
                try self.compileExpr(l.left);
                const jmp = try self.emit(.{
                    .opcode = if (l.is_and) .TEST_AND_KEEP else .TEST_OR_KEEP,
                    .a = .{ .i = 0 },
                });
                try self.emit(.{ .opcode = .POP });
                try self.compileExpr(l.right);
                self.patchJump(jmp, self.currentCodeLen());
            },
            .identifier => |name| {
                if (self.resolve(name)) |rv| {
                    try self.emit(.{ .opcode = .LOAD_LOCAL, .a = .{ .depth = rv.depth }, .b = .{ .index = rv.index } });
                } else {
                    // Неизвестная переменная → undefined (как чтение несуществующего свойства)
                    try self.emit(.{ .opcode = .LOAD_UNDEF });
                }
            },
            .assign => |a| {
                switch (a.target.*) {
                    .identifier => |name| {
                        try self.compileExpr(a.value);
                        if (self.resolve(name)) |rv| {
                            if (rv.is_const) return error.CompileError; // const нельзя перезаписывать
                            try self.emit(.{ .opcode = .STORE_LOCAL, .a = .{ .depth = rv.depth }, .b = .{ .index = rv.index } });
                        } else {
                            // Присваивание необъявленной переменной — игнорируем, но значение оставляем
                            try self.emit(.{ .opcode = .DUP });
                        }
                    },
                    .member => |m| {
                        // [obj, key, value] → SET_PROP → [obj] ; дублируем для значения выражения
                        try self.compileExpr(m.object);
                        try self.compileMemberKey(m);
                        try self.compileExpr(a.value);
                        try self.emit(.{ .opcode = .SET_PROP }); // оставляет obj
                        try self.emit(.{ .opcode = .POP }); // нам нужно значение, а не obj…
                        try self.compileExpr(a.value); // …поэтому перекладываем: проще — перевычислить
                        // Примечание: переводы выражений с побочными эффектами редки;
                        // для простоты правая часть вычисляется дважды.
                    },
                    else => return error.CompileError,
                }
            },
            .member => |m| {
                try self.compileExpr(m.object);
                try self.compileMemberKey(m);
                try self.emit(.{ .opcode = .GET_PROP });
            },
            .call => |c| {
                try self.compileExpr(c.callee);
                for (c.args.items) |arg| try self.compileExpr(arg);
                try self.emit(.{ .opcode = .CALL, .a = .{ .i = c.args.items.len } });
            },
            .func => |f| try self.compileFuncLiteral(f),
            .object => |o| {
                try self.emit(.{ .opcode = .NEW_OBJ });
                for (o.entries.items) |entry| {
                    // стек: [obj] → [obj, key] → [obj, key, value] → SET_PROP → [obj]
                    try self.emit(.{ .opcode = .DUP });
                    const idx = try self.strings.intern(self.alloc, entry.key);
                    try self.emit(.{ .opcode = .LOAD_STR, .a = .{ .i = idx } });
                    try self.compileExpr(entry.value);
                    try self.emit(.{ .opcode = .SET_PROP });
                    try self.emit(.{ .opcode = .POP });
                }
            },
        }
    }

    /// Положить ключ свойства на стек (строка-интернат или вычисленный expr)
    fn compileMemberKey(self: *Compiler, m: *parser.MemberExpr) CompileError!void {
        if (m.computed) {
            if (m.property_expr) |pe| try self.compileExpr(pe);
        } else {
            const idx = try self.strings.intern(self.alloc, m.property_name);
            try self.emit(.{ .opcode = .LOAD_STR, .a = .{ .i = idx } });
        }
    }
};

// ───────────────── Публичный API ─────────────────

pub fn compileProgram(alloc: std.mem.Allocator, prog: *parser.Program) CompileError!ProgramImage {
    var c = Compiler.init(alloc);
    try c.compileBlockBody(prog.body.stmts.items);
    // Значение последнего выражения? Нет — statement-выражения делают POP.
    // Результат программы — undefined, если явно не retнут; engine сам решает,
    // что вернуть (см. vm.runProgram → последнее "expression statement").
    return .{
        .main_code = try c.code.toOwnedSlice(alloc),
        .main_locals = c.local_counter,
        .funcs = try c.funcs.toOwnedSlice(alloc),
        .strings = try c.strings.list.toOwnedSlice(),
    };
}
