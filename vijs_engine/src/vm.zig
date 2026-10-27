const std = @import("std");
const compiler = @import("compiler.zig");
const parser = @import("parser.zig");

const STACK_SIZE = 256; // Маленький стек для экономии памяти

pub fn execute(allocator: std.mem.Allocator, bytecode: []compiler.Instruction) !parser.Expr {
    var stack: [STACK_SIZE]f64 = undefined;
    var sp: usize = 0; // stack pointer

    for (bytecode) |inst| {
        switch (inst.opcode) {
            .LOAD_CONST => {
                if (sp >= STACK_SIZE) return error.StackOverflow;
                stack[sp] = inst.operand;
                sp += 1;
            },
            .ADD => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                stack[sp] = a + b;
                sp += 1;
            },
            .SUB => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                stack[sp] = a - b;
                sp += 1;
            },
            .MUL => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                stack[sp] = a * b;
                sp += 1;
            },
            .DIV => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                if (b == 0) return error.DivisionByZero;
                sp -= 2;
                stack[sp] = a / b;
                sp += 1;
            },
        }
    }

    if (sp != 1) return error.InvalidProgram;
    
    const result = try allocator.create(parser.Expr);
    result.* = .{ .number = stack[0] };
    return result.*;
}
