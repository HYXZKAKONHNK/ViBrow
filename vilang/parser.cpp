#include <algorithm>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace vilang {

enum class TokenType {
    End,
    Newline,
    Indent,
    Dedent,
    Identifier,
    Integer,
    Float,
    String,
    Let,
    Const,
    Def,
    Fn,
    Try,
    Catch,
    If,
    Elif,
    Else,
    While,
    For,
    In,
    Return,
    Break,
    Continue,
    And,
    Or,
    Not,
    True,
    False,
    Null,
    Class,
    Pass,
    Import,
    From,
    As,
    Load,
    Library,
    File,
    LeftParen,
    RightParen,
    LeftBracket,
    RightBracket,
    LeftBrace,
    RightBrace,
    Comma,
    Dot,
    Colon,
    Semicolon,
    Plus,
    Increment,
    Minus,
    Decrement,
    Star,
    Slash,
    FloorSlash,
    Percent,
    Power,
    Bang,
    Equal,
    Less,
    Greater,
    PlusEqual,
    MinusEqual,
    StarEqual,
    SlashEqual,
    FloorSlashEqual,
    PercentEqual,
    PowerEqual,
    EqualEqual,
    BangEqual,
    LessEqual,
    GreaterEqual,
    Arrow,
    AndAnd,
    OrOr,
    BitAnd,
    BitOr,
    BitXor,
    BitNot,
    ShiftLeft,
    ShiftRight
};

struct Token {
    TokenType type;
    std::string text;
    std::size_t line;
    std::size_t column;
};

class ParseError : public std::runtime_error {
public:
    ParseError(std::size_t line, std::size_t column, const std::string& message)
        : std::runtime_error(std::to_string(line) + ":" + std::to_string(column) +
                             ": " + message) {}
};

class Lexer {
public:
    explicit Lexer(std::string source) : source_(std::move(source)) {}

    std::vector<Token> tokenize() {
        while (!atEnd()) {
            if (atLineStart_ && delimiters_.empty()) {
                scanIndentation();
                if (atEnd()) break;
                if (atLineStart_) continue;
            }

            if (peek() == ' ' || peek() == '\t' || peek() == '\f') {
                advance();
            } else if (peek() == '\r' || peek() == '\n') {
                scanNewline();
            } else if (peek() == '#') {
                skipComment();
            } else {
                scanToken();
            }
        }

        if (!delimiters_.empty()) {
            const auto& opening = delimiters_.back();
            throw ParseError(opening.line, opening.column,
                             std::string("unclosed '") + opening.value + "'");
        }
        if (lineHasToken_) {
            add(TokenType::Newline, "\n", line_, column_);
        }
        while (indentation_.size() > 1) {
            indentation_.pop_back();
            addStructural(TokenType::Dedent);
        }
        addStructural(TokenType::End);
        return tokens_;
    }

private:
    struct Delimiter {
        char value;
        std::size_t line;
        std::size_t column;
    };

    bool atEnd() const { return position_ >= source_.size(); }

    char peek(std::size_t offset = 0) const {
        const std::size_t index = position_ + offset;
        return index < source_.size() ? source_[index] : '\0';
    }

    char advance() {
        const char value = source_[position_++];
        ++column_;
        return value;
    }

    bool match(char expected) {
        if (atEnd() || peek() != expected) return false;
        advance();
        return true;
    }

    static bool isDigit(char c) { return c >= '0' && c <= '9'; }

    static bool isIdentifierStart(char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
    }

    static bool isIdentifierPart(char c) {
        return isIdentifierStart(c) || isDigit(c);
    }

    static int digitValue(char c) {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    }

    void add(TokenType type, std::string text, std::size_t line, std::size_t column) {
        tokens_.push_back({type, std::move(text), line, column});
        if (type != TokenType::Newline && type != TokenType::Indent &&
            type != TokenType::Dedent && type != TokenType::End) {
            lineHasToken_ = true;
        }
    }

    void addFromSource(TokenType type, std::size_t start, std::size_t line,
                       std::size_t column) {
        add(type, source_.substr(start, position_ - start), line, column);
    }

    void addStructural(TokenType type) { add(type, "", line_, 1); }

    void scanIndentation() {
        std::size_t width = 0;
        while (peek() == ' ' || peek() == '\t') {
            width = advance() == '\t' ? ((width / 8) + 1) * 8 : width + 1;
        }
        if (atEnd() || peek() == '#' || peek() == '\r' || peek() == '\n') {
            atLineStart_ = false;
            return;
        }
        if (width > indentation_.back()) {
            indentation_.push_back(width);
            addStructural(TokenType::Indent);
        } else if (width < indentation_.back()) {
            while (indentation_.size() > 1 && width < indentation_.back()) {
                indentation_.pop_back();
                addStructural(TokenType::Dedent);
            }
            if (width != indentation_.back()) {
                throw ParseError(line_, 1, "inconsistent indentation");
            }
        }
        atLineStart_ = false;
    }

    void scanNewline() {
        const std::size_t newlineLine = line_;
        const std::size_t newlineColumn = column_;
        if (advance() == '\r' && peek() == '\n') advance();
        if (delimiters_.empty()) {
            if (lineHasToken_) add(TokenType::Newline, "\n", newlineLine, newlineColumn);
            lineHasToken_ = false;
            atLineStart_ = true;
        } else {
            atLineStart_ = false;
        }
        ++line_;
        column_ = 1;
    }

    void skipComment() {
        while (!atEnd() && peek() != '\r' && peek() != '\n') advance();
    }

    void scanToken() {
        const std::size_t start = position_;
        const std::size_t startLine = line_;
        const std::size_t startColumn = column_;
        const char c = advance();

        if (isIdentifierStart(c)) {
            scanIdentifier(start, startLine, startColumn);
            return;
        }
        if (isDigit(c)) {
            scanNumber(start, startLine, startColumn, false);
            return;
        }
        if (c == '.' && isDigit(peek())) {
            scanNumber(start, startLine, startColumn, true);
            return;
        }
        if (c == '"' || c == '\'') {
            scanString(start, startLine, startColumn, c);
            return;
        }

        switch (c) {
        case '(': openDelimiter(TokenType::LeftParen, c, startLine, startColumn); return;
        case '[': openDelimiter(TokenType::LeftBracket, c, startLine, startColumn); return;
        case '{': openDelimiter(TokenType::LeftBrace, c, startLine, startColumn); return;
        case ')': closeDelimiter(TokenType::RightParen, ')', start, startLine, startColumn); return;
        case ']': closeDelimiter(TokenType::RightBracket, ']', start, startLine, startColumn); return;
        case '}': closeDelimiter(TokenType::RightBrace, '}', start, startLine, startColumn); return;
        case ',': addFromSource(TokenType::Comma, start, startLine, startColumn); return;
        case '.': addFromSource(TokenType::Dot, start, startLine, startColumn); return;
        case ':': addFromSource(TokenType::Colon, start, startLine, startColumn); return;
        case ';': addFromSource(TokenType::Semicolon, start, startLine, startColumn); return;
        case '+':
            addFromSource(match('+') ? TokenType::Increment
                           : match('=') ? TokenType::PlusEqual : TokenType::Plus,
                          start, startLine, startColumn);
            return;
        case '-':
            if (match('>')) addFromSource(TokenType::Arrow, start, startLine, startColumn);
            else addFromSource(match('-') ? TokenType::Decrement
                                : match('=') ? TokenType::MinusEqual : TokenType::Minus,
                               start, startLine, startColumn);
            return;
        case '*':
            if (match('*')) addFromSource(match('=') ? TokenType::PowerEqual : TokenType::Power,
                                          start, startLine, startColumn);
            else addFromSource(match('=') ? TokenType::StarEqual : TokenType::Star,
                               start, startLine, startColumn);
            return;
        case '/':
            if (match('/')) addFromSource(match('=') ? TokenType::FloorSlashEqual : TokenType::FloorSlash,
                                          start, startLine, startColumn);
            else addFromSource(match('=') ? TokenType::SlashEqual : TokenType::Slash,
                               start, startLine, startColumn);
            return;
        case '%':
            addFromSource(match('=') ? TokenType::PercentEqual : TokenType::Percent,
                          start, startLine, startColumn);
            return;
        case '!':
            addFromSource(match('=') ? TokenType::BangEqual : TokenType::Bang,
                          start, startLine, startColumn);
            return;
        case '=':
            addFromSource(match('=') ? TokenType::EqualEqual : TokenType::Equal,
                          start, startLine, startColumn);
            return;
        case '<':
            if (match('<')) addFromSource(TokenType::ShiftLeft, start, startLine, startColumn);
            else addFromSource(match('=') ? TokenType::LessEqual : TokenType::Less,
                               start, startLine, startColumn);
            return;
        case '>':
            if (match('>')) addFromSource(TokenType::ShiftRight, start, startLine, startColumn);
            else addFromSource(match('=') ? TokenType::GreaterEqual : TokenType::Greater,
                               start, startLine, startColumn);
            return;
        case '&':
            addFromSource(match('&') ? TokenType::AndAnd : TokenType::BitAnd,
                          start, startLine, startColumn);
            return;
        case '|':
            addFromSource(match('|') ? TokenType::OrOr : TokenType::BitOr,
                          start, startLine, startColumn);
            return;
        case '^': addFromSource(TokenType::BitXor, start, startLine, startColumn); return;
        case '~': addFromSource(TokenType::BitNot, start, startLine, startColumn); return;
        default:
            throw ParseError(startLine, startColumn,
                             std::string("unexpected character '") + c + "'");
        }
    }

    void scanIdentifier(std::size_t start, std::size_t line, std::size_t column) {
        while (isIdentifierPart(peek())) advance();
        const std::string text = source_.substr(start, position_ - start);
        static const std::unordered_map<std::string, TokenType> keywords{
            {"let", TokenType::Let}, {"const", TokenType::Const},
            {"def", TokenType::Def}, {"fn", TokenType::Fn},
            {"try", TokenType::Try}, {"catch", TokenType::Catch},
            {"if", TokenType::If},
            {"elif", TokenType::Elif}, {"else", TokenType::Else},
            {"while", TokenType::While}, {"for", TokenType::For},
            {"in", TokenType::In}, {"return", TokenType::Return},
            {"break", TokenType::Break}, {"continue", TokenType::Continue},
            {"and", TokenType::And}, {"or", TokenType::Or},
            {"not", TokenType::Not}, {"true", TokenType::True},
            {"false", TokenType::False}, {"null", TokenType::Null},
            {"class", TokenType::Class}, {"pass", TokenType::Pass},
            {"import", TokenType::Import}, {"from", TokenType::From},
            {"as", TokenType::As}, {"load", TokenType::Load},
            {"library", TokenType::Library}, {"file", TokenType::File}
        };
        const auto keyword = keywords.find(text);
        add(keyword == keywords.end() ? TokenType::Identifier : keyword->second,
            text, line, column);
    }

    void scanDigits(int base, std::size_t line, std::size_t column,
                    bool hasInitialDigit = false) {
        bool hasDigit = hasInitialDigit;
        bool previousWasUnderscore = false;
        while (!atEnd()) {
            if (peek() == '_') {
                if (!hasDigit || previousWasUnderscore) {
                    throw ParseError(line, column, "misplaced '_' in number");
                }
                previousWasUnderscore = true;
                advance();
                continue;
            }
            const int value = digitValue(peek());
            if (value < 0 || value >= base) break;
            hasDigit = true;
            previousWasUnderscore = false;
            advance();
        }
        if (!hasDigit || previousWasUnderscore) {
            throw ParseError(line, column, "invalid number");
        }
    }

    void scanNumber(std::size_t start, std::size_t line, std::size_t column,
                    bool leadingDot) {
        bool isFloat = leadingDot;
        if (leadingDot) {
            scanDigits(10, line, column);
        } else if (source_[start] == '0' &&
                   (peek() == 'x' || peek() == 'X' || peek() == 'b' ||
                    peek() == 'B' || peek() == 'o' || peek() == 'O')) {
            const char prefix = advance();
            const int base = (prefix == 'x' || prefix == 'X') ? 16
                           : (prefix == 'b' || prefix == 'B') ? 2 : 8;
            scanDigits(base, line, column);
            if (isDigit(peek()) || isIdentifierStart(peek())) {
                throw ParseError(line, column, "invalid digit in number");
            }
            addFromSource(TokenType::Integer, start, line, column);
            return;
        } else {
            scanDigits(10, line, column, true);
        }

        if (!leadingDot && peek() == '.' && isDigit(peek(1))) {
            isFloat = true;
            advance();
            scanDigits(10, line, column);
        }
        if (peek() == 'e' || peek() == 'E') {
            isFloat = true;
            advance();
            if (peek() == '+' || peek() == '-') advance();
            scanDigits(10, line, column);
        }
        if (isIdentifierStart(peek())) {
            throw ParseError(line, column, "invalid character after number");
        }
        addFromSource(isFloat ? TokenType::Float : TokenType::Integer,
                      start, line, column);
    }

    void scanString(std::size_t start, std::size_t line, std::size_t column,
                    char quote) {
        while (!atEnd() && peek() != quote) {
            if (peek() == '\r' || peek() == '\n') {
                throw ParseError(line, column, "unterminated string");
            }
            if (peek() == '\\') {
                advance();
                if (atEnd() || peek() == '\r' || peek() == '\n') {
                    throw ParseError(line, column, "unterminated escape sequence");
                }
            }
            advance();
        }
        if (atEnd()) throw ParseError(line, column, "unterminated string");
        advance();
        addFromSource(TokenType::String, start, line, column);
    }

    void openDelimiter(TokenType type, char value, std::size_t line,
                       std::size_t column) {
        delimiters_.push_back({value, line, column});
        addFromSource(type, position_ - 1, line, column);
    }

    void closeDelimiter(TokenType type, char value, std::size_t start,
                        std::size_t line, std::size_t column) {
        if (delimiters_.empty()) {
            throw ParseError(line, column, "unexpected closing delimiter");
        }
        const char opening = delimiters_.back().value;
        const bool matches = (opening == '(' && value == ')') ||
                             (opening == '[' && value == ']') ||
                             (opening == '{' && value == '}');
        if (!matches) throw ParseError(line, column, "mismatched closing delimiter");
        delimiters_.pop_back();
        addFromSource(type, start, line, column);
    }

    std::string source_;
    std::size_t position_ = 0;
    std::size_t line_ = 1;
    std::size_t column_ = 1;
    bool atLineStart_ = true;
    bool lineHasToken_ = false;
    std::vector<std::size_t> indentation_{0};
    std::vector<Delimiter> delimiters_;
    std::vector<Token> tokens_;
};

struct Node {
    std::string kind;
    std::string value;
    std::size_t line;
    std::vector<Node> children;
};

static Node node(std::string kind, std::string value, std::size_t line) {
    return {std::move(kind), std::move(value), line, {}};
}

class Parser {
public:
    explicit Parser(std::vector<Token> tokens) : tokens_(std::move(tokens)) {}

    Node parse() {
        Node program = node("Program", "", current().line);
        skipNewlines();
        while (!check(TokenType::End)) {
            if (match(TokenType::Dedent)) {
                throw error(previous(), "unexpected dedentation");
            }
            if (match(TokenType::Indent)) {
                throw error(previous(), "unexpected indentation");
            }
            program.children.push_back(parseStatement());
            skipNewlines();
        }
        return program;
    }

private:
    const Token& current() const { return tokens_[position_]; }
    const Token& previous() const { return tokens_[position_ - 1]; }

    bool check(TokenType type) const { return current().type == type; }

    bool match(TokenType type) {
        if (!check(type)) return false;
        ++position_;
        return true;
    }

    const Token& consume(TokenType type, const std::string& message) {
        if (!check(type)) throw error(current(), message);
        return tokens_[position_++];
    }

    static ParseError error(const Token& token, const std::string& message) {
        return ParseError(token.line, token.column, message);
    }

    void skipNewlines() {
        while (match(TokenType::Newline)) {}
    }

    bool isStatementEnd() const {
        return check(TokenType::Newline) || check(TokenType::Dedent) ||
               check(TokenType::End);
    }

    void finishSimpleStatement() {
        if (match(TokenType::Semicolon)) return;
        if (match(TokenType::Newline) || check(TokenType::Dedent) || check(TokenType::End)) {
            return;
        }
        throw error(current(), "expected end of statement");
    }

    Node parseStatement() {
        if (match(TokenType::Let) || match(TokenType::Const)) {
            return parseVariableDeclaration(previous());
        }
        if (match(TokenType::Def) || match(TokenType::Fn)) {
            return parseFunction(previous());
        }
        if (match(TokenType::Class)) return parseClass(previous());
        if (match(TokenType::If)) return parseIf(previous());
        if (match(TokenType::While)) return parseWhile(previous());
        if (match(TokenType::For)) return parseFor(previous());
        if (match(TokenType::Try)) return parseTry(previous());
        if (match(TokenType::Return)) return parseReturn(previous());
        if (match(TokenType::Break)) {
            Node result = node("Break", "", previous().line);
            finishSimpleStatement();
            return result;
        }
        if (match(TokenType::Continue)) {
            Node result = node("Continue", "", previous().line);
            finishSimpleStatement();
            return result;
        }
        if (match(TokenType::Pass)) {
            Node result = node("Pass", "", previous().line);
            finishSimpleStatement();
            return result;
        }
        if (match(TokenType::Load)) return parseLoad(previous());
        if (match(TokenType::Import)) return parseImport(previous());
        if (match(TokenType::From)) return parseFromImport(previous());

        Node expression = parseExpression();
        if (isAssignmentOperator(current().type)) {
            const Token operation = tokens_[position_++];
            if (!isAssignable(expression)) {
                throw error(operation, "invalid assignment target");
            }
            Node assignment = node("Assignment", operation.text, operation.line);
            assignment.children.push_back(std::move(expression));
            assignment.children.push_back(parseExpression());
            finishSimpleStatement();
            return assignment;
        }
        Node statement = node("ExpressionStatement", "", expression.line);
        statement.children.push_back(std::move(expression));
        finishSimpleStatement();
        return statement;
    }

    Node parseVariableDeclaration(const Token& keyword) {
        const bool isConst = keyword.type == TokenType::Const;
        const Token& name = consume(TokenType::Identifier, "expected a variable name");
        Node declaration = node(isConst ? "ConstantDeclaration" : "VariableDeclaration",
                                name.text, keyword.line);
        if (match(TokenType::Colon)) {
            declaration.value += ": " + parseTypeName();
        }
        consume(TokenType::Equal, "expected '=' after variable declaration");
        declaration.children.push_back(parseExpression());
        finishSimpleStatement();
        return declaration;
    }

    std::string parseTypeName() {
        const Token& first = consume(TokenType::Identifier, "expected a type name");
        std::string typeName = first.text;
        while (match(TokenType::Dot)) {
            typeName += "." + consume(TokenType::Identifier, "expected a type name").text;
        }
        while (match(TokenType::LeftBracket)) {
            typeName += "[";
            typeName += parseTypeName();
            consume(TokenType::RightBracket, "expected ']' after type argument");
            typeName += "]";
        }
        return typeName;
    }

    Node parseFunction(const Token& keyword) {
        const Token& name = consume(TokenType::Identifier, "expected a function name");
        Node function = node("Function", name.text, keyword.line);
        consume(TokenType::LeftParen, "expected '(' after function name");
        if (!check(TokenType::RightParen)) {
            do {
                const Token& parameter =
                    consume(TokenType::Identifier, "expected a parameter name");
                Node item = node("Parameter", parameter.text, parameter.line);
                if (match(TokenType::Colon)) {
                    item.value += ": " + parseTypeName();
                }
                if (match(TokenType::Equal)) {
                    item.children.push_back(parseExpression());
                }
                function.children.push_back(std::move(item));
            } while (match(TokenType::Comma) && !check(TokenType::RightParen));
        }
        consume(TokenType::RightParen, "expected ')' after parameters");
        if (match(TokenType::Arrow)) {
            const std::string resultType = parseTypeName();
            function.value += " -> " + resultType;
        }
        consume(TokenType::Colon, "expected ':' after function signature");
        function.children.push_back(parseSuite());
        return function;
    }

    Node parseClass(const Token& keyword) {
        const Token& name = consume(TokenType::Identifier, "expected a class name");
        Node type = node("Class", name.text, keyword.line);
        if (match(TokenType::LeftParen)) {
            if (!check(TokenType::RightParen)) {
                do {
                    type.children.push_back(parseExpression());
                } while (match(TokenType::Comma) && !check(TokenType::RightParen));
            }
            consume(TokenType::RightParen, "expected ')' after base classes");
        }
        consume(TokenType::Colon, "expected ':' after class name");
        type.children.push_back(parseSuite());
        return type;
    }

    Node parseIf(const Token& keyword) {
        Node statement = node("If", "", keyword.line);
        Node branch = node("Branch", "", keyword.line);
        branch.children.push_back(parseExpression());
        consume(TokenType::Colon, "expected ':' after if condition");
        branch.children.push_back(parseSuite());
        statement.children.push_back(std::move(branch));

        while (match(TokenType::Elif)) {
            const Token elif = previous();
            Node alternative = node("Branch", "", elif.line);
            alternative.children.push_back(parseExpression());
            consume(TokenType::Colon, "expected ':' after elif condition");
            alternative.children.push_back(parseSuite());
            statement.children.push_back(std::move(alternative));
        }
        if (match(TokenType::Else)) {
            const Token otherwise = previous();
            consume(TokenType::Colon, "expected ':' after else");
            Node alternative = node("Else", "", otherwise.line);
            alternative.children.push_back(parseSuite());
            statement.children.push_back(std::move(alternative));
        }
        return statement;
    }

    Node parseWhile(const Token& keyword) {
        Node statement = node("While", "", keyword.line);
        statement.children.push_back(parseExpression());
        consume(TokenType::Colon, "expected ':' after while condition");
        statement.children.push_back(parseSuite());
        return statement;
    }

    Node parseFor(const Token& keyword) {
        const Token& variable = consume(TokenType::Identifier, "expected a loop variable");
        consume(TokenType::In, "expected 'in' after loop variable");
        Node statement = node("For", variable.text, keyword.line);
        statement.children.push_back(parseExpression());
        consume(TokenType::Colon, "expected ':' after for expression");
        statement.children.push_back(parseSuite());
        return statement;
    }

    Node parseTry(const Token& keyword) {
        Node statement = node("Try", "", keyword.line);
        consume(TokenType::Colon, "expected ':' after try");
        statement.children.push_back(parseSuite());
        consume(TokenType::Catch, "expected 'catch' after try block");
        std::string errorName = "error";
        if (check(TokenType::Identifier)) errorName = tokens_[position_++].text;
        consume(TokenType::Colon, "expected ':' after catch");
        Node handler = node("Catch", errorName, previous().line);
        handler.children.push_back(parseSuite());
        statement.children.push_back(std::move(handler));
        return statement;
    }

    Node parseReturn(const Token& keyword) {
        Node statement = node("Return", "", keyword.line);
        if (!isStatementEnd() && !check(TokenType::Semicolon)) {
            statement.children.push_back(parseExpression());
        }
        finishSimpleStatement();
        return statement;
    }

    Node parseSuite() {
        if (!match(TokenType::Newline)) {
            Node suite = node("Block", "", current().line);
            suite.children.push_back(parseStatement());
            while (!isStatementEnd()) {
                suite.children.push_back(parseStatement());
            }
            return suite;
        }
        skipNewlines();
        consume(TokenType::Indent, "expected an indented block");
        Node suite = node("Block", "", previous().line);
        while (!check(TokenType::Dedent) && !check(TokenType::End)) {
            if (match(TokenType::Newline)) continue;
            suite.children.push_back(parseStatement());
        }
        consume(TokenType::Dedent, "expected the end of the block");
        return suite;
    }

    Node parseImport(const Token& keyword) {
        Node statement = node("Import", "", keyword.line);
        do {
            Node item = node("Module", parseDottedName(), previous().line);
            if (match(TokenType::As)) {
                item.value += " as " +
                              consume(TokenType::Identifier, "expected an import alias").text;
            }
            statement.children.push_back(std::move(item));
        } while (match(TokenType::Comma));
        finishSimpleStatement();
        return statement;
    }

    Node parseLoad(const Token& keyword) {
        if (match(TokenType::File)) {
            const Token& path = consume(TokenType::String, "expected a file path");
            Node statement = node("LoadFile", path.text, keyword.line);
            finishSimpleStatement();
            return statement;
        }
        consume(TokenType::Library, "expected 'library' or 'file' after 'load'");
        const Token& library = consume(TokenType::Identifier, "expected a library name");
        Node statement = node("LoadLibrary", library.text, keyword.line);
        finishSimpleStatement();
        return statement;
    }

    Node parseFromImport(const Token& keyword) {
        Node statement = node("FromImport", parseDottedName(), keyword.line);
        consume(TokenType::Import, "expected 'import' after module name");
        do {
            const Token& name =
                consume(TokenType::Identifier, "expected an imported name");
            Node item = node("ImportedName", name.text, name.line);
            if (match(TokenType::As)) {
                item.value += " as " +
                              consume(TokenType::Identifier, "expected an import alias").text;
            }
            statement.children.push_back(std::move(item));
        } while (match(TokenType::Comma));
        finishSimpleStatement();
        return statement;
    }

    std::string parseDottedName() {
        std::string result = consume(TokenType::Identifier, "expected a module name").text;
        while (match(TokenType::Dot)) {
            result += "." + consume(TokenType::Identifier, "expected a module name").text;
        }
        return result;
    }

    Node parseExpression(int minimumBindingPower = 0) {
        Node left = parsePrefix();
        left = parsePostfix(std::move(left));
        while (true) {
            const auto [leftPower, rightPower] = infixBinding(current().type);
            if (leftPower < minimumBindingPower) break;
            const Token operation = tokens_[position_++];
            Node binary = node("Binary", operation.text, operation.line);
            binary.children.push_back(std::move(left));
            binary.children.push_back(parseExpression(rightPower));
            left = std::move(binary);
        }
        return left;
    }

    Node parsePrefix() {
        const Token token = tokens_[position_++];
        switch (token.type) {
        case TokenType::Identifier:
            if (token.text == "array" && match(TokenType::LeftBracket)) {
                Node array = node("Array", "", token.line);
                if (!check(TokenType::RightBracket)) {
                    do {
                        array.children.push_back(parseExpression());
                    } while (match(TokenType::Comma) && !check(TokenType::RightBracket));
                }
                consume(TokenType::RightBracket, "expected ']' after array");
                return array;
            }
            return node("Identifier", token.text, token.line);
        case TokenType::Integer: return node("Integer", token.text, token.line);
        case TokenType::Float: return node("Float", token.text, token.line);
        case TokenType::String: return node("String", token.text, token.line);
        case TokenType::True: return node("Boolean", "true", token.line);
        case TokenType::False: return node("Boolean", "false", token.line);
        case TokenType::Null: return node("Null", "null", token.line);
        case TokenType::Minus:
        case TokenType::Plus:
        case TokenType::Bang:
        case TokenType::BitNot:
        case TokenType::Not: {
            Node unary = node("Unary", token.text, token.line);
            unary.children.push_back(parseExpression(11));
            return unary;
        }
        case TokenType::Increment:
        case TokenType::Decrement: {
            Node unary = node("UnaryIncrement", token.text, token.line);
            unary.children.push_back(parseExpression(11));
            if (!isAssignable(unary.children.front())) {
                throw error(token, "increment target must be assignable");
            }
            return unary;
        }
        case TokenType::LeftParen: {
            Node expression = parseExpression();
            if (match(TokenType::Comma)) {
                Node tuple = node("Tuple", "", token.line);
                tuple.children.push_back(std::move(expression));
                while (!check(TokenType::RightParen)) {
                    tuple.children.push_back(parseExpression());
                    if (!match(TokenType::Comma)) break;
                }
                consume(TokenType::RightParen, "expected ')' after tuple");
                return tuple;
            }
            consume(TokenType::RightParen, "expected ')' after expression");
            return expression;
        }
        case TokenType::LeftBracket: {
            Node array = node("Array", "", token.line);
            if (!check(TokenType::RightBracket)) {
                do {
                    array.children.push_back(parseExpression());
                } while (match(TokenType::Comma) && !check(TokenType::RightBracket));
            }
            consume(TokenType::RightBracket, "expected ']' after array");
            return array;
        }
        case TokenType::LeftBrace: {
            Node map = node("Map", "", token.line);
            if (!check(TokenType::RightBrace)) {
                do {
                    Node entry = node("Entry", "", current().line);
                    entry.children.push_back(parseExpression());
                    consume(TokenType::Colon, "expected ':' between map key and value");
                    entry.children.push_back(parseExpression());
                    map.children.push_back(std::move(entry));
                } while (match(TokenType::Comma) && !check(TokenType::RightBrace));
            }
            consume(TokenType::RightBrace, "expected '}' after map");
            return map;
        }
        default:
            throw error(token, "expected an expression");
        }
    }

    Node parsePostfix(Node expression) {
        while (true) {
            if (match(TokenType::LeftParen)) {
                Node call = node("Call", "", previous().line);
                call.children.push_back(std::move(expression));
                if (!check(TokenType::RightParen)) {
                    do {
                        call.children.push_back(parseExpression());
                    } while (match(TokenType::Comma) && !check(TokenType::RightParen));
                }
                consume(TokenType::RightParen, "expected ')' after arguments");
                expression = std::move(call);
            } else if (match(TokenType::Dot)) {
                const Token& member =
                    consume(TokenType::Identifier, "expected a member name after '.'");
                Node access = node("Member", member.text, member.line);
                access.children.push_back(std::move(expression));
                expression = std::move(access);
            } else if (match(TokenType::LeftBracket)) {
                Node access = node("Index", "", previous().line);
                access.children.push_back(std::move(expression));
                access.children.push_back(parseExpression());
                consume(TokenType::RightBracket, "expected ']' after index");
                expression = std::move(access);
            } else if (match(TokenType::Increment) || match(TokenType::Decrement)) {
                const Token operation = previous();
                if (!isAssignable(expression)) {
                    throw error(operation, "increment target must be assignable");
                }
                Node update = node("PostfixIncrement", operation.text, operation.line);
                update.children.push_back(std::move(expression));
                expression = std::move(update);
            } else {
                return expression;
            }
        }
    }

    static std::pair<int, int> infixBinding(TokenType type) {
        switch (type) {
        case TokenType::Or:
        case TokenType::OrOr: return {1, 2};
        case TokenType::And:
        case TokenType::AndAnd: return {2, 3};
        case TokenType::BitOr: return {3, 4};
        case TokenType::BitXor: return {4, 5};
        case TokenType::BitAnd: return {5, 6};
        case TokenType::EqualEqual:
        case TokenType::BangEqual: return {6, 7};
        case TokenType::Less:
        case TokenType::LessEqual:
        case TokenType::Greater:
        case TokenType::GreaterEqual:
        case TokenType::In: return {7, 8};
        case TokenType::ShiftLeft:
        case TokenType::ShiftRight: return {8, 9};
        case TokenType::Plus:
        case TokenType::Minus: return {9, 10};
        case TokenType::Star:
        case TokenType::Slash:
        case TokenType::FloorSlash:
        case TokenType::Percent: return {10, 11};
        case TokenType::Power: return {12, 12};
        default: return {-1, -1};
        }
    }

    static bool isAssignmentOperator(TokenType type) {
        switch (type) {
        case TokenType::Equal:
        case TokenType::PlusEqual:
        case TokenType::MinusEqual:
        case TokenType::StarEqual:
        case TokenType::SlashEqual:
        case TokenType::FloorSlashEqual:
        case TokenType::PercentEqual:
        case TokenType::PowerEqual: return true;
        default: return false;
        }
    }

    static bool isAssignable(const Node& expression) {
        return expression.kind == "Identifier" || expression.kind == "Member" ||
               expression.kind == "Index";
    }

    const std::vector<Token> tokens_;
    std::size_t position_ = 0;
};

static void printTree(const Node& current, std::ostream& output,
                      const std::string& prefix, bool isLast, bool isRoot = false) {
    if (!isRoot) output << prefix << (isLast ? "`- " : "|- ");
    output << current.kind;
    if (!current.value.empty()) output << " (" << current.value << ')';
    output << '\n';

    const std::string childPrefix =
        isRoot ? "" : prefix + (isLast ? "   " : "|  ");
    for (std::size_t i = 0; i < current.children.size(); ++i) {
        printTree(current.children[i], output, childPrefix,
                  i + 1 == current.children.size());
    }
}

} // namespace vilang

int main(int argc, char* argv[]) {
    if (argc > 2) {
        std::cerr << "Usage: vilang-parser [source-file]\n";
        return 2;
    }

    std::ifstream file;
    std::istream* input = &std::cin;
    if (argc == 2) {
        file.open(argv[1], std::ios::binary);
        if (!file) {
            std::cerr << "Cannot open source file: " << argv[1] << '\n';
            return 2;
        }
        input = &file;
    }

    std::ostringstream source;
    source << input->rdbuf();
    if (input->bad()) {
        std::cerr << "Failed to read source input\n";
        return 2;
    }

    try {
        vilang::Lexer lexer(source.str());
        vilang::Parser parser(lexer.tokenize());
        const vilang::Node program = parser.parse();
        vilang::printTree(program, std::cout, "", true, true);
    } catch (const vilang::ParseError& error) {
        std::cerr << "ViLang parser error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}