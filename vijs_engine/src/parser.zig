const std = @import("std");
const lexer = @import("lexer.zig");

// ═══════════════════════════════════════════════════════════════
// AST — дерево разбора. Выражения (Expr) и операторы (Stmt).
// Поддерживаем: let/const/var, функции (closures), вызовы, объекты,
// if/else, сравнения, строки, свойства через . и [].
// ═══════════════════════════════════════════════════════════════

pub const BinOp = enum {
    add,
    sub,
    mul,
    div,
    mod,
    pow,
    eq_eq,    // ==
    eq_eq_eq, // ===
    neq,      // !=
    neq_neq,  // !==
    lt,       // <
    le,       // <=
    gt,       // >
    ge,       // >=
};

pub const Expr = union(enum) {
    number: f64,
    string: []const u8, // текст литерала (без кавычек, уже декодированный)
    identifier: []const u8,
    bool_lit: bool,
    null_lit,
    undefined_lit,
    binary: *BinaryExpr,
    logical: *LogicalExpr, // && || (ленивые)
    unary_not: *Expr,      // !x
    neg: *Expr,            // -x
    assign: *AssignExpr,   // x = expr (присваивание существующей переменной)
    member: *MemberExpr,   // obj.prop | obj[expr]
    call: *CallExpr,       // fn(args)
    func: *FuncExpr,       // function (params) { body } — closure-литерал
    object: *ObjectExpr,   // { key: value, ... }

    pub fn destroy(self: *Expr, allocator: std.mem.Allocator) void {
        switch (self.*) {
            .number, .string, .identifier, .bool_lit, .null_lit, .undefined_lit => {},
            .binary => |b| {
                b.left.destroy(allocator);
                b.right.destroy(allocator);
                allocator.destroy(b);
            },
            .logical => |l| {
                l.left.destroy(allocator);
                l.right.destroy(allocator);
                allocator.destroy(l);
            },
            .unary_not => |e| {
                e.destroy(allocator);
                allocator.destroy(e);
            },
            .neg => |e| {
                e.destroy(allocator);
                allocator.destroy(e);
            },
            .assign => |a| {
                a.target.destroy(allocator);
                a.value.destroy(allocator);
                allocator.destroy(a);
            },
            .member => |m| {
                m.object.destroy(allocator);
                if (m.computed) {
                    if (m.property_expr) |pe| {
                        pe.destroy(allocator);
                        allocator.destroy(pe);
                    }
                }
                allocator.destroy(m);
            },
            .call => |c| {
                c.callee.destroy(allocator);
                for (c.args.items) |*arg| arg.destroy(allocator);
                c.args.deinit();
                allocator.destroy(c);
            },
            .func => |f| {
                allocator.free(f.name);
                for (f.params.items) |p| allocator.free(p);
                f.params.deinit();
                f.body.destroy(allocator);
                allocator.destroy(f.body);
                allocator.destroy(f);
            },
            .object => |o| {
                for (o.entries.items) |e| {
                    allocator.free(e.key);
                    var v = e.value;
                    v.destroy(allocator);
                    allocator.destroy(v);
                }
                o.entries.deinit();
                allocator.destroy(o);
            },
        }
    }
};

pub const BinaryExpr = struct {
    op: BinOp,
    left: *Expr,
    right: *Expr,
};

pub const LogicalExpr = struct {
    is_and: bool, // true → &&, false → ||
    left: *Expr,
    right: *Expr,
};

pub const AssignExpr = struct {
    target: *Expr, // identifier или member
    value: *Expr,
};

pub const MemberExpr = struct {
    object: *Expr,
    property_name: []const u8, // для obj.prop
    computed: bool,            // true для obj[expr]
    property_expr: ?*Expr,     // для obj[expr]
};

pub const CallExpr = struct {
    callee: *Expr,
    args: std.ArrayList(*Expr),
};

pub const FuncExpr = struct {
    name: []const u8, // '' для анонимных
    params: std.ArrayList([]const u8),
    body: *BlockStmt,
};

pub const ObjectEntry = struct {
    key: []const u8,
    value: *Expr,
};

pub const ObjectExpr = struct {
    entries: std.ArrayList(ObjectEntry),
};

// ───────── Операторы (statements) ─────────

pub const DeclKind = enum { let_decl, const_decl, var_decl };

pub const Stmt = union(enum) {
    expr: *Expr,          // выражение как оператор (x = 5; foo();)
    decl: *DeclStmt,      // let/const/var
    return_stmt: ?*Expr,  // return [expr]
    if_stmt: *IfStmt,     // if (...) ... else ...
    block: *BlockStmt,    // { ... }
    func_decl: *FuncExpr, // function f() {} — объявление с именем

    pub fn destroy(self: *Stmt, allocator: std.mem.Allocator) void {
        switch (self.*) {
            .expr => |e| {
                e.destroy(allocator);
                allocator.destroy(e);
            },
            .decl => |d| {
                d.value_opt.destroy(allocator);
                allocator.destroy(d.value_opt);
                allocator.free(d.name);
                allocator.destroy(d);
            },
            .return_stmt => |maybe_e| {
                if (maybe_e) |e| {
                    e.destroy(allocator);
                    allocator.destroy(e);
                }
            },
            .if_stmt => |ifs| {
                ifs.condition.destroy(allocator);
                allocator.destroy(ifs.condition);
                ifs.consequent.destroy(allocator);
                allocator.destroy(ifs.consequent);
                if (ifs.alternate) |alt| {
                    alt.destroy(allocator);
                    allocator.destroy(alt);
                }
                allocator.destroy(ifs);
            },
            .block => |blk| {
                blk.destroy(allocator);
                allocator.destroy(blk);
            },
            .func_decl => |f| {
                f.body.destroy(allocator);
                allocator.destroy(f.body);
                for (f.params.items) |p| allocator.free(p);
                f.params.deinit();
                allocator.free(f.name);
                allocator.destroy(f);
            },
        }
    }
};

pub const DeclStmt = struct {
    kind: DeclKind,
    name: []const u8,
    value_opt: *Expr, // если инициализатора нет — подставлен undefined_lit
};

pub const IfStmt = struct {
    condition: *Expr,
    consequent: *Stmt, // обычно block
    alternate: ?*Stmt,
};

pub const BlockStmt = struct {
    stmts: std.ArrayList(*Stmt),

    pub fn destroy(self: *BlockStmt, allocator: std.mem.Allocator) void {
        for (self.stmts.items) |s| s.destroy(allocator);
        self.stmts.deinit();
    }
};

pub const Program = struct {
    body: BlockStmt, // верхнеуровневый блок

    pub fn destroy(self: *Program, allocator: std.mem.Allocator) void {
        self.body.destroy(allocator);
    }
};

// Явный error set — разрывает цикл вывода ошибок при рекурсии (Zig 0.17)
pub const ParseErr = error{ ParseError, OutOfMemory };

fn tokTypeToBinOp(t: lexer.TokenType) ?BinOp {
    return switch (t) {
        .plus => .add,
        .minus => .sub,
        .multiply => .mul,
        .divide => .div,
        .modulo => .mod,
        .power => .pow,
        .eq_eq => .eq_eq,
        .eq_eq_eq => .eq_eq_eq,
        .neq => .neq,
        .neq_neq => .neq_neq,
        .less => .lt,
        .less_eq => .le,
        .greater => .gt,
        .greater_eq => .ge,
        else => null,
    };
}

/// Приоритет бинарных операторов (чем выше, тем сильнее связывает)
fn binPrecedence(op: BinOp) u8 {
    return switch (op) {
        .eq_eq, .eq_eq_eq, .neq, .neq_neq => 1,
        .lt, .le, .gt, .ge => 2,
        .add, .sub => 3,
        .mul, .div, .mod => 4,
        .pow => 5,
    };
}

/// '**' — правоассоциативный: 2 ** 3 ** 2 == 2 ** (3 ** 2)
fn isRightAssociative(op: BinOp) bool {
    return op == .pow;
}

fn isKeywordLike(t: lexer.TokenType) bool {
    return switch (t) {
        .kw_let, .kw_const, .kw_var, .kw_function, .kw_return, .kw_if, .kw_else, .kw_true, .kw_false, .kw_null, .kw_undefined => true,
        else => false,
    };
}

pub const Parser = struct {
    tokens: []const lexer.Token,
    current: usize,
    allocator: std.mem.Allocator,

    fn peek(self: *Parser) lexer.Token {
        return self.tokens[self.current];
    }

    fn consume(self: *Parser) lexer.Token {
        const token = self.tokens[self.current];
        if (token.type != .eof) self.current += 1;
        return token;
    }

    fn expect(self: *Parser, t: lexer.TokenType) ParseErr!void {
        if (self.peek().type != t) return error.ParseError;
        _ = self.consume();
    }

    /// ; или конец блока/программы — необязательные терминаторы
    fn eatSemicolon(self: *Parser) void {
        if (self.peek().type == .semicolon) _ = self.consume();
    }

    // ───────── Программа ─────────

    fn parseProgramInner(self: *Parser) ParseErr!*Program {
        var body = std.ArrayList(*Stmt).init(self.allocator);
        while (self.peek().type != .eof) {
            const s = try self.parseStatement();
            try body.append(s);
        }
        const prog = try self.allocator.create(Program);
        prog.* = .{ .body = .{ .stmts = body } };
        return prog;
    }

    // ───────── Операторы ─────────

    fn parseStatement(self: *Parser) ParseErr!*Stmt {
        const tok = self.peek();
        const st = try self.allocator.create(Stmt);
        switch (tok.type) {
            .kw_let, .kw_const, .kw_var => return self.parseDecl(st),
            .kw_function => return self.parseFuncDecl(st),
            .kw_return => {
                _ = self.consume();
                var val: ?*Expr = null;
                const nt = self.peek().type;
                if (nt != .semicolon and nt != .right_brace and nt != .eof) {
                    val = try self.parseExpression(0);
                }
                self.eatSemicolon();
                st.* = .{ .return_stmt = val };
                return st;
            },
            .kw_if => return self.parseIf(st),
            .left_brace => {
                const blk = try self.parseBlock();
                st.* = .{ .block = blk };
                return st;
            },
            .semicolon => {
                _ = self.consume(); // пустой оператор
                const e = try self.allocator.create(Expr);
                e.* = .undefined_lit;
                st.* = .{ .expr = e };
                return st;
            },
            else => {
                const e = try self.parseExpression(0);
                self.eatSemicolon();
                st.* = .{ .expr = e };
                return st;
            },
        }
    }

    fn parseDecl(self: *Parser, st: *Stmt) ParseErr!*Stmt {
        const kind_tok = self.consume();
        const kind: DeclKind = switch (kind_tok.type) {
            .kw_let => .let_decl,
            .kw_const => .const_decl,
            .kw_var => .var_decl,
            else => return error.ParseError,
        };
        const name_tok = self.consume();
        if (name_tok.type != .identifier) return error.ParseError;
        const name = try self.allocator.dupe(u8, name_tok.value);

        var value_opt: *Expr = undefined;
        if (self.peek().type == .assign) {
            _ = self.consume();
            value_opt = try self.parseExpression(0);
        } else {
            value_opt = try self.allocator.create(Expr);
            value_opt.* = .undefined_lit;
        }
        self.eatSemicolon();
        st.* = .{ .decl = .{
            .kind = kind,
            .name = name,
            .value_opt = value_opt,
        } };
        return st;
    }

    fn parseFuncDecl(self: *Parser, st: *Stmt) ParseErr!*Stmt {
        const f = try self.parseFunction();
        if (f.name.len == 0) return error.ParseError; // объявление требует имени
        st.* = .{ .func_decl = f };
        return st;
    }

    fn parseIf(self: *Parser, st: *Stmt) ParseErr!*Stmt {
        _ = self.consume(); // 'if'
        try self.expect(.left_paren);
        const cond = try self.parseExpression(0);
        try self.expect(.right_paren);

        const cons = try self.parseStatement();
        var alt: ?*Stmt = null;
        if (self.peek().type == .kw_else) {
            _ = self.consume();
            alt = try self.parseStatement();
        }
        st.* = .{ .if_stmt = .{
            .condition = cond,
            .consequent = cons,
            .alternate = alt,
        } };
        return st;
    }

    fn parseBlock(self: *Parser) ParseErr!*BlockStmt {
        try self.expect(.left_brace);
        var stmts = std.ArrayList(*Stmt).init(self.allocator);
        while (self.peek().type != .right_brace) {
            if (self.peek().type == .eof) return error.ParseError;
            const s = try self.parseStatement();
            try stmts.append(s);
        }
        try self.expect(.right_brace);
        const blk = try self.allocator.create(BlockStmt);
        blk.* = .{ .stmts = stmts };
        return blk;
    }

    /// Вызывается когда текущий токен — 'function'
    fn parseFunction(self: *Parser) ParseErr!*FuncExpr {
        _ = self.consume(); // 'function'
        var name: []const u8 = "";
        if (self.peek().type == .identifier) {
            name = try self.allocator.dupe(u8, self.consume().value);
        }
        try self.expect(.left_paren);
        var params = std.ArrayList([]const u8).init(self.allocator);
        while (self.peek().type != .right_paren) {
            if (self.peek().type == .eof) return error.ParseError;
            const pt = self.consume();
            if (pt.type != .identifier) return error.ParseError;
            try params.append(try self.allocator.dupe(u8, pt.value));
            if (self.peek().type == .comma) _ = self.consume();
        }
        try self.expect(.right_paren);
        const body = try self.parseBlock();
        const f = try self.allocator.create(FuncExpr);
        f.* = .{ .name = name, .params = params, .body = body };
        return f;
    }

    // ───────── Выражения ─────────

    fn parseExpression(self: *Parser, min_prec: u8) ParseErr!*Expr {
        return self.parseLogical(min_prec);
    }

    /// Логические && и || — левые, приоритет ниже всех бинарных (0)
    fn parseLogical(self: *Parser, min_prec: u8) ParseErr!*Expr {
        var left = try self.parseBinary(min_prec);
        while (min_prec == 0) {
            const t = self.peek().type;
            var is_and = false;
            switch (t) {
                .and_and => is_and = true,
                .or_or => is_and = false,
                else => break,
            }
            _ = self.consume();
            const right = try self.parseBinary(0); // левая ассоциативность
            const l = try self.allocator.create(LogicalExpr);
            l.* = .{ .is_and = is_and, .left = left, .right = right };
            const e = try self.allocator.create(Expr);
            e.* = .{ .logical = l };
            left = e;
        }
        return left;
    }

    fn parseBinary(self: *Parser, min_prec: u8) ParseErr!*Expr {
        var left = try self.parsePostfix();

        while (true) {
            const op = tokTypeToBinOp(self.peek().type) orelse break;
            const prec = binPrecedence(op);
            if (prec <= min_prec) break;

            _ = self.consume(); // съедаем оператор
            const right = try self.parseBinary(if (isRightAssociative(op)) prec - 1 else prec);

            const bin = try self.allocator.create(BinaryExpr);
            bin.* = .{ .op = op, .left = left, .right = right };

            const expr = try self.allocator.create(Expr);
            expr.* = .{ .binary = bin };
            left = expr;
        }

        return left;
    }

    fn isAssignable(e: *Expr) bool {
        return switch (e.*) {
            .identifier, .member => true,
            else => false,
        };
    }

    /// Постфиксы: вызовы fn(...), обращения obj.prop / obj[expr], присваивание.
    fn parsePostfix(self: *Parser) ParseErr!*Expr {
        var left = try self.parsePrimary();

        loop: while (true) {
            switch (self.peek().type) {
                .left_paren => {
                    _ = self.consume();
                    var args = std.ArrayList(*Expr).init(self.allocator);
                    while (self.peek().type != .right_paren) {
                        if (self.peek().type == .eof) return error.ParseError;
                        const a = try self.parseExpression(0);
                        try args.append(a);
                        if (self.peek().type == .comma) _ = self.consume();
                    }
                    _ = self.consume(); // ')'
                    const c = try self.allocator.create(CallExpr);
                    c.* = .{ .callee = left, .args = args };
                    const e = try self.allocator.create(Expr);
                    e.* = .{ .call = c };
                    left = e;
                },
                .dot => {
                    _ = self.consume();
                    const pt = self.consume();
                    if (pt.type != .identifier and pt.type != .string and !isKeywordLike(pt.type)) {
                        return error.ParseError;
                    }
                    const m = try self.allocator.create(MemberExpr);
                    m.* = .{ .object = left, .property_name = pt.value, .computed = false, .property_expr = null };
                    const e = try self.allocator.create(Expr);
                    e.* = .{ .member = m };
                    left = e;
                },
                .left_bracket => {
                    _ = self.consume();
                    const idx = try self.parseExpression(0);
                    try self.expect(.right_bracket);
                    const m = try self.allocator.create(MemberExpr);
                    m.* = .{ .object = left, .property_name = "", .computed = true, .property_expr = idx };
                    const e = try self.allocator.create(Expr);
                    e.* = .{ .member = m };
                    left = e;
                },
                .assign => {
                    // x = ..., obj.p = ... — присваивание (правая часть парсится заново)
                    if (!isAssignable(left)) return error.ParseError;
                    _ = self.consume();
                    const value = try self.parseExpression(0);
                    const a = try self.allocator.create(AssignExpr);
                    a.* = .{ .target = left, .value = value };
                    const e = try self.allocator.create(Expr);
                    e.* = .{ .assign = a };
                    left = e;
                },
                else => break :loop,
            }
        }
        return left;
    }

    fn parsePrimary(self: *Parser) ParseErr!*Expr {
        // Унарные минус/плюс/bang: -5, -(2+3), !x
        const next_tok = self.peek();
        if (next_tok.type == .minus or next_tok.type == .plus or next_tok.type == .bang) {
            _ = self.consume();
            const operand = try self.parsePrimary();
            const e = try self.allocator.create(Expr);
            switch (next_tok.type) {
                .minus => e.* = .{ .neg = operand },
                .bang => e.* = .{ .unary_not = operand },
                else => { // +x — no-op
                    e.* = operand.*;
                    self.allocator.destroy(operand);
                },
            }
            return e;
        }
        return self.parseAtom();
    }

    fn parseAtom(self: *Parser) ParseErr!*Expr {
        const token = self.consume();
        const expr = try self.allocator.create(Expr);

        switch (token.type) {
            .number => {
                expr.* = .{ .number = std.fmt.parseFloat(f64, token.value) catch return error.ParseError };
                return expr;
            },
            .string => {
                expr.* = .{ .string = token.value };
                return expr;
            },
            .identifier => {
                expr.* = .{ .identifier = token.value };
                return expr;
            },
            .kw_true => {
                expr.* = .{ .bool_lit = true };
                return expr;
            },
            .kw_false => {
                expr.* = .{ .bool_lit = false };
                return expr;
            },
            .kw_null => {
                expr.* = .null_lit;
                return expr;
            },
            .kw_undefined => {
                expr.* = .undefined_lit;
                return expr;
            },
            .kw_function => {
                const f = try self.parseFunction();
                expr.* = .{ .func = f };
                return expr;
            },
            .left_paren => {
                const inner = try self.parseExpression(0);
                try self.expect(.right_paren);
                self.allocator.destroy(expr);
                return inner;
            },
            .left_brace => {
                // Литерал объекта { a: 1, "b": 2, if: 3 }
                var entries = std.ArrayList(ObjectEntry).init(self.allocator);
                while (self.peek().type != .right_brace) {
                    if (self.peek().type == .eof) return error.ParseError;
                    const kt = self.consume();
                    var key: []const u8 = undefined;
                    switch (kt.type) {
                        .identifier, .string => key = kt.value,
                        else => {
                            if (!isKeywordLike(kt.type)) return error.ParseError;
                            key = kt.value;
                        },
                    }
                    // Ключ должен быть продублирован: он указывает в исходник токенов,
                    // а токены живут только до конца компиляции — дупим.
                    try entries.append(.{ .key = try self.allocator.dupe(u8, key), .value = blk_val: {
                        try self.expect(.colon);
                        break :blk_val try self.parseExpression(0);
                    } });
                    if (self.peek().type == .comma) _ = self.consume();
                }
                try self.expect(.right_brace);
                const o = try self.allocator.create(ObjectExpr);
                o.* = .{ .entries = entries };
                expr.* = .{ .object = o };
                return expr;
            },
            else => return error.ParseError,
        }
    }
};

/// Старый API: разбор одного выражения (для совместимости).
pub fn parse(allocator: std.mem.Allocator, tokens: []const lexer.Token) ParseErr!*Expr {
    var p = Parser{ .tokens = tokens, .current = 0, .allocator = allocator };
    const ast = try p.parseExpression(0);
    if (p.peek().type != .eof) return error.ParseError;
    return ast;
}

/// Новый API: разбор полной программы.
pub fn parseProgram(allocator: std.mem.Allocator, tokens: []const lexer.Token) ParseErr!*Program {
    var p = Parser{ .tokens = tokens, .current = 0, .allocator = allocator };
    return p.parseProgramInner();
}



