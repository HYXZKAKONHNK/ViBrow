const std = @import("std");

pub const TokenType = enum {
    number,
    identifier,
    plus,
    minus,
    multiply,
    divide,
    left_paren,
    right_paren,
    equal,
    semicolon,
    eof,
};

pub const Token = struct {
    type: TokenType,
    value: []const u8,
    position: usize,
};

pub fn tokenize(allocator: std.mem.Allocator, source: []const u8) ![]Token {
    var tokens = std.ArrayList(Token).init(allocator);
    var i: usize = 0;

    while (i < source.len) {
        // Пропускаем пробелы
        if (std.ascii.isWhitespace(source[i])) {
            i += 1;
            continue;
        }

        const start = i;
        const ch = source[i];

        switch (ch) {
            '0'...'9' => {
                // Читаем число
                while (i < source.len and (std.ascii.isDigit(source[i]) or source[i] == '.')) {
                    i += 1;
                }
                try tokens.append(.{
                    .type = .number,
                    .value = source[start..i],
                    .position = start,
                });
            },
            'a'...'z', 'A'...'Z', '_' => {
                // Читаем идентификатор (имя переменной)
                while (i < source.len and (std.ascii.isAlphanumeric(source[i]) or source[i] == '_')) {
                    i += 1;
                }
                try tokens.append(.{
                    .type = .identifier,
                    .value = source[start..i],
                    .position = start,
                });
            },
            '+' => {
                try tokens.append(.{ .type = .plus, .value = "+", .position = i });
                i += 1;
            },
            '-' => {
                try tokens.append(.{ .type = .minus, .value = "-", .position = i });
                i += 1;
            },
            '*' => {
                try tokens.append(.{ .type = .multiply, .value = "*", .position = i });
                i += 1;
            },
            '/' => {
                try tokens.append(.{ .type = .divide, .value = "/", .position = i });
                i += 1;
            },
            '(' => {
                try tokens.append(.{ .type = .left_paren, .value = "(", .position = i });
                i += 1;
            },
            ')' => {
                try tokens.append(.{ .type = .right_paren, .value = ")", .position = i });
                i += 1;
            },
            '=' => {
                try tokens.append(.{ .type = .equal, .value = "=", .position = i });
                i += 1;
            },
            ';' => {
                try tokens.append(.{ .type = .semicolon, .value = ";", .position = i });
                i += 1;
            },
            else => {
                return error.LexerError;
            },
        }
    }

    try tokens.append(.{ .type = .eof, .value = "", .position = i });
    return tokens.toOwnedSlice();
}
