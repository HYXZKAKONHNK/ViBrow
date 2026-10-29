const std = @import("std");

pub const TokenType = enum {
    number,
    identifier,
    plus,
    minus,
    multiply,
    divide,
    modulo,     // % — остаток (bank scripts: хеши, чекауты)
    power,      // ** — возведение в степень
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
                // '**' — возведение в степень (правоассоциативное)
                if (i + 1 < source.len and source[i + 1] == '*') {
                    try tokens.append(.{ .type = .power, .value = "**", .position = i });
                    i += 2;
                    continue;
                }
                try tokens.append(.{ .type = .multiply, .value = "*", .position = i });
                i += 1;
            },
            '/' => {
                // Пропускаем комментарии: // до конца строки и /* ... */
                if (i + 1 < source.len and source[i + 1] == '/') {
                    while (i < source.len and source[i] != '\n') i += 1;
                    continue;
                }
                if (i + 1 < source.len and source[i + 1] == '*') {
                    i += 2;
                    while (i + 1 < source.len and !(source[i] == '*' and source[i + 1] == '/')) i += 1;
                    if (i + 1 >= source.len) return error.LexerError;
                    i += 2;
                    continue;
                }
                try tokens.append(.{ .type = .divide, .value = "/", .position = i });
                i += 1;
            },
            '%' => {
                try tokens.append(.{ .type = .modulo, .value = "%", .position = i });
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

    return tokens.toOwnedSlice();
}
