const std = @import("std");
const lexer = @import("lexer.zig");

// Узлы AST для выражений
pub const Expr = union(enum) {
    number: f64,
    binary: BinaryExpr,
    
    pub fn destroy(self: *Expr, allocator: std.mem.Allocator) void {
        switch (self.*) {
            .binary => |*bin| {
                bin.left.destroy(allocator);
                bin.right.destroy(allocator);
                allocator.destroy(bin.left);
                allocator.destroy(bin.right);
            },
            .number => {},
        }
    }
};

pub const BinaryExpr = struct {
    op: lexer.TokenType,
    left: *Expr,
    right: *Expr,
};

pub const Parser = struct {
    tokens: []const lexer.Token,
    current: usize,
    allocator: std.mem.Allocator,

    pub fn parse(allocator: std.mem.Allocator, tokens: []const lexer.Token) !*Expr {
        var parser = Parser{
            .tokens = tokens,
            .current = 0,
            .allocator = allocator,
        };
        return parser.parseExpression(0);
    }

    fn peek(self: *Parser) lexer.Token {
        return self.tokens[self.current];
    }

    fn consume(self: *Parser) lexer.Token {
        const token = self.tokens[self.current];
        self.current += 1;
        return token;
    }

    // Приоритет операторов (чем выше, тем сильнее связывает)
    fn precedence(op: lexer.TokenType) u8 {
        return switch (op) {
            .plus, .minus => 1,
            .multiply, .divide => 2,
            else => 0,
        };
    }

    // Рекурсивный спуск с учетом приоритетов
    fn parseExpression(self: *Parser, min_prec: u8) !*Expr {
        var left = try self.parsePrimary();

        while (true) {
            const op = self.peek().type;
            const prec = precedence(op);
            if (prec <= min_prec) break;

            _ = self.consume(); // съедаем оператор
            const right = try self.parseExpression(prec);

            const bin = try self.allocator.create(BinaryExpr);
            bin.* = .{ .op = op, .left = left, .right = right };
            
            const expr = try self.allocator.create(Expr);
            expr.* = .{ .binary = bin.* };
            left = expr;
        }

        return left;
    }

    fn parsePrimary(self: *Parser) !*Expr {
        const token = self.consume();
        const expr = try self.allocator.create(Expr);

        switch (token.type) {
            .number => {
                expr.* = .{ .number = std.fmt.parseFloat(f64, token.value) catch return error.ParseError };
                return expr;
            },
            .left_paren => {
                const inner = try self.parseExpression(0);
                if (self.peek().type != .right_paren) return error.ParseError;
                _ = self.consume();
                return inner;
            },
            else => return error.ParseError,
        }
    }
};

pub fn parse(allocator: std.mem.Allocator, tokens: []const lexer.Token) !*Expr {
    return Parser.parse(allocator, tokens);
}
