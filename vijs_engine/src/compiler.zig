const std = @import("std");
const parser = @import("parser.zig");
const lexer = @import("lexer.zig");

// Инструкции байткода
pub const Opcode = enum(u8) {
    LOAD_CONST = 0,
    ADD = 1,
    SUB = 2,
    MUL = 3,
    DIV = 4,
    MOD = 5,
    POW = 6,
};

pub const Instruction = struct {
    opcode: Opcode,
    operand: f64, // Для LOAD_CONST
};

pub fn compile(allocator: std.mem.Allocator, ast: *parser.Expr) ![]Instruction {
    var code = std.ArrayList(Instruction).init(allocator);
    try compileExpr(&code, ast);
    return code.toOwnedSlice();
}

fn compileExpr(code: *std.ArrayList(Instruction), expr: *parser.Expr) !void {
    switch (expr.*) {
        .number => |n| {
            try code.append(.{ .opcode = .LOAD_CONST, .operand = n });
        },
        .binary => |bin| {
            try compileExpr(code, bin.left);
            try compileExpr(code, bin.right);
            
            const op = switch (bin.op) {
                .plus => Opcode.ADD,
                .minus => Opcode.SUB,
                .multiply => Opcode.MUL,
                .divide => Opcode.DIV,
                .modulo => Opcode.MOD,
                .power => Opcode.POW,
                else => return error.CompileError,
            };
            try code.append(.{ .opcode = op, .operand = 0 });
        },
    }
}
