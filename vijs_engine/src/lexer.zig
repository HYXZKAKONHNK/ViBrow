const std = @import("std");

pub const TokenType = enum {
    number,
    string,       // "текст" или 'текст' — литерал строки
    identifier,
    // ─── Ключевые слова ───
    kw_let,       // let
    kw_const,     // const
    kw_var,       // var
    kw_function,  // function
    kw_return,    // return
    kw_if,        // if
    kw_else,      // else
    kw_true,      // true
    kw_false,     // false
    kw_null,      // null
    kw_undefined, // undefined
    // ─── Операторы и пунктуация ───
    plus,
    minus,
    multiply,
    divide,
    modulo,     // % — остаток (bank scripts: хеши, чекауты)
    power,      // ** — возведение в степень
    assign,     // =  (присваивание; раньше был .equal)
    eq_eq,      // ==
    eq_eq_eq,   // ===
    neq,        // !=
    neq_neq,    // !==
    less,       // <
    less_eq,    // <=
    greater,    // >
    greater_eq, // >=
    and_and,    // &&
    or_or,      // ||
    bang,       // !
    left_paren,
    right_paren,
    left_brace,  // {
    right_brace, // }
    left_bracket, // [
    right_bracket, // ]
    dot,          // .
    comma,        // ,
    colon,        // :
    semicolon,
    eof,
};

pub const Token = struct {
    type: TokenType,
    value: []const u8,
    position: usize,
};

/// Ключевые слова: сопоставление текста токена с типом
fn keywordType(text: []const u8) ?TokenType {
    const map = std.StaticStringMap(TokenType).initComptime(.{
        .{ "let", .kw_let },
        .{ "const", .kw_const },
        .{ "var", .kw_var },
        .{ "function", .kw_function },
        .{ "return", .kw_return },
        .{ "if", .kw_if },
        .{ "else", .kw_else },
        .{ "true", .kw_true },
        .{ "false", .kw_false },
        .{ "null", .kw_null },
        .{ "undefined", .kw_undefined },
    });
    return map.get(text);
}

/// Экранирование внутри строк: \n \t \r \\ \' \" \0 \<иной> → сам символ
fn appendUnescaped(buf: *std.ArrayList(u8), src: []const u8) !void {
    var j: usize = 0;
    while (j < src.len) {
        if (src[j] == '\\' and j + 1 < src.len) {
            j += 1;
            const c: u8 = switch (src[j]) {
                'n' => '\n',
                't' => '\t',
                'r' => '\r',
                '0' => 0,
                else => src[j], // \\ \' \" и прочие — как есть
            };
            try buf.append(c);
        } else {
            try buf.append(src[j]);
        }
        j += 1;
    }
}

pub fn tokenize(allocator: std.mem.Allocator, source: []const u8) ![]Token {
    var tokens = std.ArrayList(Token).init(allocator);
    var str_buf = std.ArrayList(u8).init(allocator); // временный буфер для строк
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
            'a'...'z', 'A'...'Z', '_', '$' => {
                // Идентификатор или ключевое слово
                while (i < source.len and (std.ascii.isAlphanumeric(source[i]) or source[i] == '_' or source[i] == '$')) {
                    i += 1;
                }
                const text = source[start..i];
                const kw = keywordType(text);
                try tokens.append(.{
                    .type = kw orelse TokenType.identifier,
                    .value = text,
                    .position = start,
                });
            },
            '"' '\'' => {
                // Строковый литерал: "..." или '...', с поддержкой экранирования
                const quote = ch;
                i += 1;
                str_buf.clearRetainingCapacity();
                while (true) {
                    if (i >= source.len) return error.LexerError; // незакрытая строка
                    if (source[i] == quote) break;
                    if (source[i] == '\\' and i + 1 < source.len) {
                        try appendUnescaped(&str_buf, source[i .. i + 2]);
                        i += 2;
                        continue;
                    }
                    if (source[i] == '\n') return error.LexerError; // многострочные без переноса
                    try str_buf.append(source[i]);
                    i += 1;
                }
                i += 1; // закрывающая кавычка
                const duped = try str_buf.toOwnedSlice();
                try tokens.append(.{
                    .type = .string,
                    .value = duped, // декодированное содержимое (без кавычек)
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
            '{' => {
                try tokens.append(.{ .type = .left_brace, .value = "{", .position = i });
                i += 1;
            },
            '}' => {
                try tokens.append(.{ .type = .right_brace, .value = "}", .position = i });
                i += 1;
            },
            '[' => {
                try tokens.append(.{ .type = .left_bracket, .value = "[", .position = i });
                i += 1;
            },
            ']' => {
                try tokens.append(.{ .type = .right_bracket, .value = "]", .position = i });
                i += 1;
            },
            '.' => {
                try tokens.append(.{ .type = .dot, .value = ".", .position = i });
                i += 1;
            },
            ',' => {
                try tokens.append(.{ .type = .comma, .value = ",", .position = i });
                i += 1;
            },
            ':' => {
                try tokens.append(.{ .type = .colon, .value = ":", .position = i });
                i += 1;
            },
            ';' => {
                try tokens.append(.{ .type = .semicolon, .value = ";", .position = i });
                i += 1;
            },
            '=' => {
                // === , == , =
                if (i + 2 < source.len and source[i + 1] == '=' and source[i + 2] == '=') {
                    try tokens.append(.{ .type = .eq_eq_eq, .value = "===", .position = i });
                    i += 3;
                } else if (i + 1 < source.len and source[i + 1] == '=') {
                    try tokens.append(.{ .type = .eq_eq, .value = "==", .position = i });
                    i += 2;
                } else {
                    try tokens.append(.{ .type = .assign, .value = "=", .position = i });
                    i += 1;
                }
            },
            '!' => {
                // !== , != , !
                if (i + 2 < source.len and source[i + 1] == '=' and source[i + 2] == '=') {
                    try tokens.append(.{ .type = .neq_neq, .value = "!==", .position = i });
                    i += 3;
                } else if (i + 1 < source.len and source[i + 1] == '=') {
                    try tokens.append(.{ .type = .neq, .value = "!=", .position = i });
                    i += 2;
                } else {
                    try tokens.append(.{ .type = .bang, .value = "!", .position = i });
                    i += 1;
                }
            },
            '<' => {
                if (i + 1 < source.len and source[i + 1] == '=') {
                    try tokens.append(.{ .type = .less_eq, .value = "<=", .position = i });
                    i += 2;
                } else {
                    try tokens.append(.{ .type = .less, .value = "<", .position = i });
                    i += 1;
                }
            },
            '>' => {
                if (i + 1 < source.len and source[i + 1] == '=') {
                    try tokens.append(.{ .type = .greater_eq, .value = ">=", .position = i });
                    i += 2;
                } else {
                    try tokens.append(.{ .type = .greater, .value = ">", .position = i });
                    i += 1;
                }
            },
            '&' => {
                if (i + 1 < source.len and source[i + 1] == '&') {
                    try tokens.append(.{ .type = .and_and, .value = "&&", .position = i });
                    i += 2;
                } else return error.LexerError;
            },
            '|' => {
                if (i + 1 < source.len and source[i + 1] == '|') {
                    try tokens.append(.{ .type = .or_or, .value = "||", .position = i });
                    i += 2;
                } else return error.LexerError;
            },
            else => {
                return error.LexerError;
            },
        }
    }

    try tokens.append(.{ .type = .eof, .value = "", .position = i });
    return tokens.toOwnedSlice();
}
