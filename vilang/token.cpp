#include <cctype>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

enum class TokenType {
    EndOfFile,
    Newline,
    Indent,
    Dedent,
    Identifier,
    Integer,
    Float,
    String,
    KwLet,
    KwConst,
    KwDef,
    KwFn,
    KwTry,
    KwCatch,
    KwIf,
    KwElif,
    KwElse,
    KwWhile,
    KwFor,
    KwIn,
    KwReturn,
    KwBreak,
    KwContinue,
    KwAnd,
    KwOr,
    KwNot,
    KwTrue,
    KwFalse,
    KwNull,
    KwClass,
    KwPass,
    KwImport,
    KwFrom,
    KwAs,
    KwLoad,
    KwLibrary,
    KwFile,
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
    std::string lexeme;
    std::size_t line;
    std::size_t column;
};

class LexerError : public std::runtime_error {
public:
    LexerError(std::size_t line, std::size_t column, const std::string& message)
        : std::runtime_error(
              std::to_string(line) + ":" + std::to_string(column) + ": " + message) {}
};

class Lexer {
public:
    explicit Lexer(std::string source) : source_(std::move(source)) {}

    std::vector<Token> tokenize() {
        while (!atEnd()) {
            if (atLineStart_ && delimiters_.empty()) {
                scanIndentation();
                if (atEnd()) {
                    break;
                }
                if (atLineStart_) {
                    continue;
                }
            }

            const char c = peek();
            if (c == ' ' || c == '\t' || c == '\f') {
                advance();
                continue;
            }
            if (c == '\r' || c == '\n') {
                scanNewline();
                continue;
            }
            if (c == '#') {
                skipComment();
                continue;
            }

            scanToken();
        }

        if (!delimiters_.empty()) {
            const auto& opening = delimiters_.back();
            throw LexerError(opening.line, opening.column,
                             std::string("unclosed '") + opening.value + "'");
        }

        if (lineHasToken_) {
            add(TokenType::Newline, "\n", line_, column_);
            lineHasToken_ = false;
        }
        while (indentation_.size() > 1) {
            indentation_.pop_back();
            addStructural(TokenType::Dedent);
        }
        addStructural(TokenType::EndOfFile);
        return tokens_;
    }

private:
    struct Delimiter {
        char value;
        std::size_t line;
        std::size_t column;
    };

    static const std::unordered_map<std::string_view, TokenType>& keywords() {
        static const std::unordered_map<std::string_view, TokenType> table{
            {"let", TokenType::KwLet},       {"const", TokenType::KwConst},
            {"def", TokenType::KwDef},       {"fn", TokenType::KwFn},
            {"try", TokenType::KwTry},       {"catch", TokenType::KwCatch},
            {"if", TokenType::KwIf},
            {"elif", TokenType::KwElif},     {"else", TokenType::KwElse},
            {"while", TokenType::KwWhile},   {"for", TokenType::KwFor},
            {"in", TokenType::KwIn},         {"return", TokenType::KwReturn},
            {"break", TokenType::KwBreak},   {"continue", TokenType::KwContinue},
            {"and", TokenType::KwAnd},       {"or", TokenType::KwOr},
            {"not", TokenType::KwNot},       {"true", TokenType::KwTrue},
            {"false", TokenType::KwFalse},   {"null", TokenType::KwNull},
            {"class", TokenType::KwClass},   {"pass", TokenType::KwPass},
            {"import", TokenType::KwImport}, {"from", TokenType::KwFrom},
            {"as", TokenType::KwAs},         {"load", TokenType::KwLoad},
            {"library", TokenType::KwLibrary}, {"file", TokenType::KwFile}
        };
        return table;
    }

    bool atEnd() const {
        return position_ >= source_.size();
    }

    char peek(std::size_t offset = 0) const {
        const std::size_t index = position_ + offset;
        return index < source_.size() ? source_[index] : '\0';
    }

    char advance() {
        const char c = source_[position_++];
        ++column_;
        return c;
    }

    bool match(char expected) {
        if (atEnd() || peek() != expected) {
            return false;
        }
        advance();
        return true;
    }

    static bool isDigit(char c) {
        return c >= '0' && c <= '9';
    }

    static bool isIdentifierStart(char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
    }

    static bool isIdentifierPart(char c) {
        return isIdentifierStart(c) || isDigit(c);
    }

    static int digitValue(char c) {
        if (c >= '0' && c <= '9') {
            return c - '0';
        }
        if (c >= 'a' && c <= 'f') {
            return c - 'a' + 10;
        }
        if (c >= 'A' && c <= 'F') {
            return c - 'A' + 10;
        }
        return -1;
    }

    void add(TokenType type, std::string lexeme, std::size_t line, std::size_t column) {
        tokens_.push_back({type, std::move(lexeme), line, column});
        if (type != TokenType::Newline && type != TokenType::Indent &&
            type != TokenType::Dedent && type != TokenType::EndOfFile) {
            lineHasToken_ = true;
        }
    }

    void addFromSource(TokenType type, std::size_t start, std::size_t line,
                       std::size_t column) {
        add(type, source_.substr(start, position_ - start), line, column);
    }

    void addStructural(TokenType type) {
        add(type, "", line_, 1);
    }

    void scanIndentation() {
        std::size_t width = 0;
        while (peek() == ' ' || peek() == '\t') {
            if (advance() == ' ') {
                ++width;
            } else {
                width = ((width / 8) + 1) * 8;
            }
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
                throw LexerError(line_, 1, "inconsistent indentation");
            }
        }
        atLineStart_ = false;
    }

    void scanNewline() {
        const std::size_t newlineLine = line_;
        const std::size_t newlineColumn = column_;
        if (peek() == '\r') {
            advance();
            if (peek() == '\n') {
                advance();
            }
        } else {
            advance();
        }

        if (delimiters_.empty()) {
            if (lineHasToken_) {
                add(TokenType::Newline, "\n", newlineLine, newlineColumn);
            }
            lineHasToken_ = false;
            atLineStart_ = true;
        } else {
            atLineStart_ = false;
        }
        ++line_;
        column_ = 1;
    }

    void skipComment() {
        while (!atEnd() && peek() != '\r' && peek() != '\n') {
            advance();
        }
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
            if (match('>')) {
                addFromSource(TokenType::Arrow, start, startLine, startColumn);
            } else {
                addFromSource(match('-') ? TokenType::Decrement
                               : match('=') ? TokenType::MinusEqual : TokenType::Minus,
                              start, startLine, startColumn);
            }
            return;
        case '*':
            if (match('*')) {
                addFromSource(match('=') ? TokenType::PowerEqual : TokenType::Power,
                              start, startLine, startColumn);
            } else {
                addFromSource(match('=') ? TokenType::StarEqual : TokenType::Star,
                              start, startLine, startColumn);
            }
            return;
        case '/':
            if (match('/')) {
                addFromSource(match('=') ? TokenType::FloorSlashEqual : TokenType::FloorSlash,
                              start, startLine, startColumn);
            } else {
                addFromSource(match('=') ? TokenType::SlashEqual : TokenType::Slash,
                              start, startLine, startColumn);
            }
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
            if (match('<')) {
                addFromSource(TokenType::ShiftLeft, start, startLine, startColumn);
            } else {
                addFromSource(match('=') ? TokenType::LessEqual : TokenType::Less,
                              start, startLine, startColumn);
            }
            return;
        case '>':
            if (match('>')) {
                addFromSource(TokenType::ShiftRight, start, startLine, startColumn);
            } else {
                addFromSource(match('=') ? TokenType::GreaterEqual : TokenType::Greater,
                              start, startLine, startColumn);
            }
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
            throw LexerError(startLine, startColumn,
                             std::string("unexpected character '") + c + "'");
        }
    }

    void scanIdentifier(std::size_t start, std::size_t line, std::size_t column) {
        while (isIdentifierPart(peek())) {
            advance();
        }
        const std::string lexeme = source_.substr(start, position_ - start);
        const auto keyword = keywords().find(lexeme);
        add(keyword == keywords().end() ? TokenType::Identifier : keyword->second,
            lexeme, line, column);
    }

    void scanDigits(int base, std::size_t line, std::size_t column,
                    bool hasInitialDigit = false) {
        bool hasDigit = hasInitialDigit;
        bool previousWasUnderscore = false;
        while (!atEnd()) {
            if (peek() == '_') {
                if (!hasDigit || previousWasUnderscore) {
                    throw LexerError(line, column, "misplaced '_' in number");
                }
                previousWasUnderscore = true;
                advance();
                continue;
            }
            const int value = digitValue(peek());
            if (value < 0 || value >= base) {
                break;
            }
            hasDigit = true;
            previousWasUnderscore = false;
            advance();
        }
        if (!hasDigit || previousWasUnderscore) {
            throw LexerError(line, column, "invalid number");
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
                throw LexerError(line, column, "invalid digit in number");
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
            if (peek() == '+' || peek() == '-') {
                advance();
            }
            scanDigits(10, line, column);
        }
        if (isIdentifierStart(peek())) {
            throw LexerError(line, column, "invalid character after number");
        }
        addFromSource(isFloat ? TokenType::Float : TokenType::Integer,
                      start, line, column);
    }

    void scanString(std::size_t start, std::size_t line, std::size_t column,
                    char quote) {
        while (!atEnd() && peek() != quote) {
            if (peek() == '\r' || peek() == '\n') {
                throw LexerError(line, column, "unterminated string");
            }
            if (peek() == '\\') {
                advance();
                if (atEnd() || peek() == '\r' || peek() == '\n') {
                    throw LexerError(line, column, "unterminated escape sequence");
                }
            }
            advance();
        }
        if (atEnd()) {
            throw LexerError(line, column, "unterminated string");
        }
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
            throw LexerError(line, column, "unexpected closing delimiter");
        }
        const char opening = delimiters_.back().value;
        const bool matches = (opening == '(' && value == ')') ||
                             (opening == '[' && value == ']') ||
                             (opening == '{' && value == '}');
        if (!matches) {
            throw LexerError(line, column, "mismatched closing delimiter");
        }
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

static const char* tokenTypeName(TokenType type) {
    switch (type) {
    case TokenType::EndOfFile: return "EOF";
    case TokenType::Newline: return "NEWLINE";
    case TokenType::Indent: return "INDENT";
    case TokenType::Dedent: return "DEDENT";
    case TokenType::Identifier: return "IDENTIFIER";
    case TokenType::Integer: return "INTEGER";
    case TokenType::Float: return "FLOAT";
    case TokenType::String: return "STRING";
    case TokenType::KwLet: return "LET";
    case TokenType::KwConst: return "CONST";
    case TokenType::KwDef: return "DEF";
    case TokenType::KwFn: return "FN";
    case TokenType::KwTry: return "TRY";
    case TokenType::KwCatch: return "CATCH";
    case TokenType::KwIf: return "IF";
    case TokenType::KwElif: return "ELIF";
    case TokenType::KwElse: return "ELSE";
    case TokenType::KwWhile: return "WHILE";
    case TokenType::KwFor: return "FOR";
    case TokenType::KwIn: return "IN";
    case TokenType::KwReturn: return "RETURN";
    case TokenType::KwBreak: return "BREAK";
    case TokenType::KwContinue: return "CONTINUE";
    case TokenType::KwAnd: return "AND";
    case TokenType::KwOr: return "OR";
    case TokenType::KwNot: return "NOT";
    case TokenType::KwTrue: return "TRUE";
    case TokenType::KwFalse: return "FALSE";
    case TokenType::KwNull: return "NULL";
    case TokenType::KwClass: return "CLASS";
    case TokenType::KwPass: return "PASS";
    case TokenType::KwImport: return "IMPORT";
    case TokenType::KwFrom: return "FROM";
    case TokenType::KwAs: return "AS";
    case TokenType::KwLoad: return "LOAD";
    case TokenType::KwLibrary: return "LIBRARY";
    case TokenType::KwFile: return "FILE";
    case TokenType::LeftParen: return "LEFT_PAREN";
    case TokenType::RightParen: return "RIGHT_PAREN";
    case TokenType::LeftBracket: return "LEFT_BRACKET";
    case TokenType::RightBracket: return "RIGHT_BRACKET";
    case TokenType::LeftBrace: return "LEFT_BRACE";
    case TokenType::RightBrace: return "RIGHT_BRACE";
    case TokenType::Comma: return "COMMA";
    case TokenType::Dot: return "DOT";
    case TokenType::Colon: return "COLON";
    case TokenType::Semicolon: return "SEMICOLON";
    case TokenType::Plus: return "PLUS";
    case TokenType::Increment: return "INCREMENT";
    case TokenType::Minus: return "MINUS";
    case TokenType::Decrement: return "DECREMENT";
    case TokenType::Star: return "STAR";
    case TokenType::Slash: return "SLASH";
    case TokenType::FloorSlash: return "FLOOR_SLASH";
    case TokenType::Percent: return "PERCENT";
    case TokenType::Power: return "POWER";
    case TokenType::Bang: return "BANG";
    case TokenType::Equal: return "EQUAL";
    case TokenType::Less: return "LESS";
    case TokenType::Greater: return "GREATER";
    case TokenType::PlusEqual: return "PLUS_EQUAL";
    case TokenType::MinusEqual: return "MINUS_EQUAL";
    case TokenType::StarEqual: return "STAR_EQUAL";
    case TokenType::SlashEqual: return "SLASH_EQUAL";
    case TokenType::FloorSlashEqual: return "FLOOR_SLASH_EQUAL";
    case TokenType::PercentEqual: return "PERCENT_EQUAL";
    case TokenType::PowerEqual: return "POWER_EQUAL";
    case TokenType::EqualEqual: return "EQUAL_EQUAL";
    case TokenType::BangEqual: return "BANG_EQUAL";
    case TokenType::LessEqual: return "LESS_EQUAL";
    case TokenType::GreaterEqual: return "GREATER_EQUAL";
    case TokenType::Arrow: return "ARROW";
    case TokenType::AndAnd: return "AND_AND";
    case TokenType::OrOr: return "OR_OR";
    case TokenType::BitAnd: return "BIT_AND";
    case TokenType::BitOr: return "BIT_OR";
    case TokenType::BitXor: return "BIT_XOR";
    case TokenType::BitNot: return "BIT_NOT";
    case TokenType::ShiftLeft: return "SHIFT_LEFT";
    case TokenType::ShiftRight: return "SHIFT_RIGHT";
    }
    return "UNKNOWN";
}

static std::string escapeForDisplay(const std::string& value) {
    std::string escaped;
    for (char c : value) {
        switch (c) {
        case '\\': escaped += "\\\\"; break;
        case '"': escaped += "\\\""; break;
        case '\n': escaped += "\\n"; break;
        case '\r': escaped += "\\r"; break;
        case '\t': escaped += "\\t"; break;
        default: escaped += c; break;
        }
    }
    return escaped;
}

int main(int argc, char* argv[]) {
    if (argc > 2) {
        std::cerr << "Usage: vilang-tokenizer [source-file]\n";
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

    std::ostringstream buffer;
    buffer << input->rdbuf();
    if (input->bad()) {
        std::cerr << "Failed to read source input\n";
        return 2;
    }

    try {
        Lexer lexer(buffer.str());
        for (const Token& token : lexer.tokenize()) {
            std::cout << token.line << ':' << token.column << '\t'
                      << tokenTypeName(token.type) << "\t\""
                      << escapeForDisplay(token.lexeme) << "\"\n";
        }
    } catch (const LexerError& error) {
        std::cerr << "ViLang tokenizer error: " << error.what() << '\n';
        return 1;
    }

    return 0;
}