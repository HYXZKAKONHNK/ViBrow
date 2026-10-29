const std = @import("std");
const js = @import("js_value.zig");
const compiler = @import("compiler.zig");

const STACK_SIZE = 256;

/// Выполняет байткод и возвращает JsValue
pub fn execute(
    allocator: std.mem.Allocator,
    bytecode: []compiler.Instruction,
) !js.JsValue {
    _ = allocator; // пока не нужен, но будет для объектов

    // Стек из JsValue — каждое значение всего 8 байт!
    var stack: [STACK_SIZE]js.JsValue = undefined;
    var sp: usize = 0;

    for (bytecode) |inst| {
        switch (inst.opcode) {
            .LOAD_CONST => {
                if (sp >= STACK_SIZE) return error.StackOverflow;
                // Загружаем число как JsValue
                stack[sp] = js.fromNumber(inst.operand);
                sp += 1;
            },
            .ADD => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                // Сложение (пока только числа)
                if (js.isNumber(a) and js.isNumber(b)) {
                    stack[sp] = js.fromNumber(js.getNumber(a) + js.getNumber(b));
                } else {
                    // TODO: конкатенация строк
                    stack[sp] = js.JS_NAN;
                }
                sp += 1;
            },
            .SUB => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                stack[sp] = js.fromNumber(js.toNumber(a) - js.toNumber(b));
                sp += 1;
            },
            .MUL => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                stack[sp] = js.fromNumber(js.toNumber(a) * js.toNumber(b));
                sp += 1;
            },
            .DIV => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                const divisor = js.toNumber(b);
                if (divisor == 0) {
                    stack[sp] = js.JS_NAN; // как в JS: 1/0 = Infinity, 0/0 = NaN
                } else {
                    stack[sp] = js.fromNumber(js.toNumber(a) / divisor);
                }
                sp += 1;
            },
            .MOD => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                const divisor = js.toNumber(b);
                if (divisor == 0) {
                    stack[sp] = js.JS_NAN; // JS: x % 0 = NaN
                } else {
                    stack[sp] = js.fromNumber(@rem(js.toNumber(a), divisor));
                }
                sp += 1;
            },
            .POW => {
                if (sp < 2) return error.StackUnderflow;
                const b = stack[sp - 1];
                const a = stack[sp - 2];
                sp -= 2;
                stack[sp] = js.fromNumber(std.math.pow(f64, js.toNumber(a), js.toNumber(b)));
                sp += 1;
            },
        }
    }

    if (sp != 1) return error.InvalidProgram;
    return stack[0];
}

    return stack[0];
}
