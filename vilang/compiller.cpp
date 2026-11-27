#include <cctype>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <unordered_set>
#include <vector>

#define VILANG_COMPILER
#include "load.cpp"
#undef VILANG_COMPILER

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
    Def,
    Fn,
    For,
    In,
    Try,
    Catch,
    Let,
    Const,
    If,
    Elif,
    Else,
    While,
    Return,
    Pass,
    True,
    False,
    Null,
    And,
    Or,
    Not,
    Load,
    Library,
    File,
    LeftParen,
    RightParen,
    LeftBracket,
    RightBracket,
    LeftBrace,
    RightBrace,
    Dot,
    Colon,
    Comma,
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
    EqualEqual,
    BangEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual
};

struct Token {
    TokenType type;
    std::string text;
    std::size_t line;
    std::size_t column;
    std::string sourceFile;
};

class CompileError : public std::runtime_error {
public:
    CompileError(std::size_t line, std::size_t column, const std::string& message)
        : std::runtime_error(std::to_string(line) + ":" + std::to_string(column) +
                             ": " + message) {}
};

class Lexer {
public:
    explicit Lexer(std::string source, std::string sourceFile = {})
        : source_(std::move(source)), sourceFile_(std::move(sourceFile)) {}

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
            throw CompileError(opening.line, opening.column,
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

    bool atEnd() const {
        return position_ >= source_.size();
    }

    char peek(std::size_t offset = 0) const {
        const auto index = position_ + offset;
        return index < source_.size() ? source_[index] : '\0';
    }

    char advance() {
        const char result = source_[position_++];
        ++column_;
        return result;
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

    void add(TokenType type, std::string text, std::size_t line, std::size_t column) {
        tokens_.push_back({type, std::move(text), line, column, sourceFile_});
        if (type != TokenType::Newline && type != TokenType::Indent &&
            type != TokenType::Dedent && type != TokenType::End) {
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
                throw CompileError(line_, 1, "inconsistent indentation");
            }
        }
        atLineStart_ = false;
    }

    void scanNewline() {
        const std::size_t newlineLine = line_;
        const std::size_t newlineColumn = column_;
        if (advance() == '\r' && peek() == '\n') {
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
        if (isDigit(c) || (c == '.' && isDigit(peek()))) {
            scanNumber(start, startLine, startColumn, c == '.');
            return;
        }
        if (c == '"' || c == '\'') {
            scanString(start, startLine, startColumn, c);
            return;
        }

        switch (c) {
        case '(':
            delimiters_.push_back({c, startLine, startColumn});
            addFromSource(TokenType::LeftParen, start, startLine, startColumn);
            return;
        case '[':
            delimiters_.push_back({c, startLine, startColumn});
            addFromSource(TokenType::LeftBracket, start, startLine, startColumn);
            return;
        case '{':
            delimiters_.push_back({c, startLine, startColumn});
            addFromSource(TokenType::LeftBrace, start, startLine, startColumn);
            return;
        case '.': addFromSource(TokenType::Dot, start, startLine, startColumn); return;
        case ')':
        case ']':
        case '}': {
            if (delimiters_.empty()) {
                throw CompileError(startLine, startColumn, "unexpected closing delimiter");
            }
            const char opening = delimiters_.back().value;
            const bool matches = (opening == '(' && c == ')') ||
                                 (opening == '[' && c == ']') ||
                                 (opening == '{' && c == '}');
            if (!matches) {
                throw CompileError(startLine, startColumn, "mismatched closing delimiter");
            }
            delimiters_.pop_back();
            const TokenType type = c == ')' ? TokenType::RightParen
                                  : c == ']' ? TokenType::RightBracket
                                             : TokenType::RightBrace;
            addFromSource(type, start, startLine, startColumn);
            return;
        }
        case ':': addFromSource(TokenType::Colon, start, startLine, startColumn); return;
        case ',': addFromSource(TokenType::Comma, start, startLine, startColumn); return;
        case ';': addFromSource(TokenType::Semicolon, start, startLine, startColumn); return;
        case '+':
            addFromSource(match('+') ? TokenType::Increment : TokenType::Plus,
                          start, startLine, startColumn);
            return;
        case '-':
            addFromSource(match('-') ? TokenType::Decrement : TokenType::Minus,
                          start, startLine, startColumn);
            return;
        case '*':
            if (match('*')) {
                addFromSource(TokenType::Power, start, startLine, startColumn);
            } else {
                addFromSource(TokenType::Star, start, startLine, startColumn);
            }
            return;
        case '/':
            if (match('/')) {
                addFromSource(TokenType::FloorSlash, start, startLine, startColumn);
            } else {
                addFromSource(TokenType::Slash, start, startLine, startColumn);
            }
            return;
        case '%': addFromSource(TokenType::Percent, start, startLine, startColumn); return;
        case '!':
            addFromSource(match('=') ? TokenType::BangEqual : TokenType::Bang,
                          start, startLine, startColumn);
            return;
        case '=':
            addFromSource(match('=') ? TokenType::EqualEqual : TokenType::Equal,
                          start, startLine, startColumn);
            return;
        case '<':
            addFromSource(match('=') ? TokenType::LessEqual : TokenType::Less,
                          start, startLine, startColumn);
            return;
        case '>':
            addFromSource(match('=') ? TokenType::GreaterEqual : TokenType::Greater,
                          start, startLine, startColumn);
            return;
        default:
            throw CompileError(startLine, startColumn,
                               std::string("unexpected character '") + c + "'");
        }
    }

    void scanIdentifier(std::size_t start, std::size_t line, std::size_t column) {
        while (isIdentifierPart(peek())) {
            advance();
        }
        const std::string text = source_.substr(start, position_ - start);
        TokenType type = TokenType::Identifier;
        if (text == "let") type = TokenType::Let;
        else if (text == "const") type = TokenType::Const;
        else if (text == "def") type = TokenType::Def;
        else if (text == "fn") type = TokenType::Fn;
        else if (text == "for") type = TokenType::For;
        else if (text == "in") type = TokenType::In;
        else if (text == "try") type = TokenType::Try;
        else if (text == "catch") type = TokenType::Catch;
        else if (text == "if") type = TokenType::If;
        else if (text == "elif") type = TokenType::Elif;
        else if (text == "else") type = TokenType::Else;
        else if (text == "while") type = TokenType::While;
        else if (text == "return") type = TokenType::Return;
        else if (text == "pass") type = TokenType::Pass;
        else if (text == "true") type = TokenType::True;
        else if (text == "false") type = TokenType::False;
        else if (text == "null") type = TokenType::Null;
        else if (text == "and") type = TokenType::And;
        else if (text == "or") type = TokenType::Or;
        else if (text == "not") type = TokenType::Not;
        else if (text == "load") type = TokenType::Load;
        else if (text == "library") type = TokenType::Library;
        else if (text == "file") type = TokenType::File;
        add(type, text, line, column);
    }

    void scanNumber(std::size_t start, std::size_t line, std::size_t column,
                    bool leadingDot) {
        bool isFloat = leadingDot;
        bool lastWasUnderscore = false;
        bool sawDigit = !leadingDot;
        while (isDigit(peek()) || peek() == '_') {
            if (peek() == '_') {
                if (!sawDigit || lastWasUnderscore) {
                    throw CompileError(line, column, "misplaced '_' in number");
                }
                lastWasUnderscore = true;
            } else {
                sawDigit = true;
                lastWasUnderscore = false;
            }
            advance();
        }
        if (lastWasUnderscore) {
            throw CompileError(line, column, "number cannot end with '_'");
        }
        if (!leadingDot && peek() == '.' && isDigit(peek(1))) {
            isFloat = true;
            advance();
            while (isDigit(peek())) advance();
        }
        if (peek() == 'e' || peek() == 'E') {
            isFloat = true;
            advance();
            if (peek() == '+' || peek() == '-') advance();
            if (!isDigit(peek())) {
                throw CompileError(line, column, "expected exponent digits");
            }
            while (isDigit(peek())) advance();
        }
        if (isIdentifierStart(peek())) {
            throw CompileError(line, column, "invalid character after number");
        }
        addFromSource(isFloat ? TokenType::Float : TokenType::Integer,
                      start, line, column);
    }

    void scanString(std::size_t start, std::size_t line, std::size_t column,
                    char quote) {
        while (!atEnd() && peek() != quote) {
            if (peek() == '\r' || peek() == '\n') {
                throw CompileError(line, column, "unterminated string");
            }
            if (peek() == '\\') {
                advance();
                if (atEnd() || peek() == '\r' || peek() == '\n') {
                    throw CompileError(line, column, "unterminated escape sequence");
                }
            }
            advance();
        }
        if (atEnd()) {
            throw CompileError(line, column, "unterminated string");
        }
        advance();
        addFromSource(TokenType::String, start, line, column);
    }

    std::string source_;
    std::string sourceFile_;
    std::size_t position_ = 0;
    std::size_t line_ = 1;
    std::size_t column_ = 1;
    bool atLineStart_ = true;
    bool lineHasToken_ = false;
    std::vector<std::size_t> indentation_{0};
    std::vector<Delimiter> delimiters_;
    std::vector<Token> tokens_;
};

struct Instruction {
    std::string operation;
    std::string argument;
    std::size_t line;
};

struct Constant {
    std::string type;
    std::string value;
};

class Compiler {
public:
    explicit Compiler(std::vector<Token> tokens) : tokens_(std::move(tokens)) {
        if (!tokens_.empty() && !tokens_.front().sourceFile.empty()) {
            loadedModules_.insert(loader::canonicalSourcePath(
                std::filesystem::u8path(tokens_.front().sourceFile)).u8string());
        }
    }

    void compile() {
        while (!check(TokenType::End)) {
            if (match(TokenType::Newline)) {
                continue;
            }
            if (match(TokenType::Indent)) {
                throw error(previous(), "unexpected indentation");
            }
            if (match(TokenType::Dedent)) {
                throw error(previous(), "unexpected dedentation");
            }
            compileStatement();
        }
        emit("HALT", "", current().line);
    }

    const std::vector<Instruction>& instructions() const {
        return instructions_;
    }

    const std::vector<Constant>& constants() const {
        return constants_;
    }

private:
    const Token& current() const {
        return tokens_[position_];
    }

    const Token& previous() const {
        return tokens_[position_ - 1];
    }

    bool check(TokenType type) const {
        return current().type == type;
    }

    bool match(TokenType type) {
        if (!check(type)) {
            return false;
        }
        ++position_;
        return true;
    }

    const Token& consume(TokenType type, const std::string& message) {
        if (!check(type)) {
            throw error(current(), message);
        }
        return tokens_[position_++];
    }

    static CompileError error(const Token& token, const std::string& message) {
        return CompileError(token.line, token.column, message);
    }

    std::size_t emit(std::string operation, std::string argument, std::size_t line) {
        instructions_.push_back({std::move(operation), std::move(argument), line});
        return instructions_.size() - 1;
    }

    std::size_t addConstant(std::string type, std::string value) {
        constants_.push_back({std::move(type), std::move(value)});
        return constants_.size() - 1;
    }

    void patchJump(std::size_t instruction, std::size_t target) {
        instructions_[instruction].argument = std::to_string(target);
    }

    void compileStatement() {
        if (match(TokenType::Load)) {
            const Token loadKeyword = previous();
            if (match(TokenType::File)) {
                compileLoadFile(loadKeyword);
                return;
            }
            consume(TokenType::Library, "expected 'library' or 'file' after 'load'");
            const Token& library = consume(TokenType::Identifier, "expected a library name");
            if (library.text != "Numbeer" && library.text != "internet" &&
                library.text != "gpu" && library.text != "time" &&
                library.text != "loader" && library.text != "Loader") {
                throw error(library, "unknown library '" + library.text + "'");
            }
            const std::string libraryName =
                library.text == "Loader" ? "loader" : library.text;
            emit("LOAD_LIBRARY", libraryName, loadKeyword.line);
            if (library.text == "Numbeer") numbeerLoaded_ = true;
            if (library.text == "internet") internetLoaded_ = true;
            if (library.text == "gpu") gpuLoaded_ = true;
            if (library.text == "time") timeLoaded_ = true;
            if (libraryName == "loader") loaderLoaded_ = true;
            finishSimpleStatement();
            return;
        }

        if (match(TokenType::Let) || match(TokenType::Const)) {
            const bool isConst = previous().type == TokenType::Const;
            const Token& name = consume(TokenType::Identifier, "expected a variable name");
            consume(TokenType::Equal, "expected '=' after variable name");
            compileExpression();
            emit(isConst ? "DEFINE_CONST" : "DEFINE_VAR", name.text, name.line);
            finishSimpleStatement();
            return;
        }

        if (match(TokenType::Def) || match(TokenType::Fn)) {
            compileFunction(previous());
            return;
        }

        if (match(TokenType::If) || match(TokenType::Elif)) {
            compileIf(previous());
            return;
        }
        if (match(TokenType::While)) {
            compileWhile(previous());
            return;
        }
        if (match(TokenType::For)) {
            compileFor(previous());
            return;
        }
        if (match(TokenType::Try)) {
            compileTryCatch(previous());
            return;
        }
        if (match(TokenType::Return)) {
            const std::size_t line = previous().line;
            if (check(TokenType::Newline) || check(TokenType::Dedent) ||
                check(TokenType::End) || check(TokenType::Semicolon)) {
                emit("RETURN_VOID", "", line);
            } else {
                compileExpression();
                emit("RETURN", "", line);
            }
            finishSimpleStatement();
            return;
        }
        if (match(TokenType::Pass)) {
            emit("NOP", "", previous().line);
            finishSimpleStatement();
            return;
        }

        if (check(TokenType::Identifier) && current().text == "print" &&
            peekType(1) == TokenType::LeftParen) {
            const Token printToken = tokens_[position_++];
            ++position_;
            compileExpression();
            consume(TokenType::RightParen, "expected ')' after print argument");
            emit("PRINT", "", printToken.line);
            finishSimpleStatement();
            return;
        }

        if (check(TokenType::Identifier) && peekType(1) == TokenType::Equal) {
            const Token name = tokens_[position_++];
            ++position_;
            compileExpression();
            emit("STORE", name.text, name.line);
            finishSimpleStatement();
            return;
        }

        if (check(TokenType::Identifier) &&
            peekType(1) == TokenType::LeftBracket) {
            const Token name = tokens_[position_++];
            emit("LOAD", name.text, name.line);
            std::size_t indexCount = 0;
            while (match(TokenType::LeftBracket)) {
                compileExpression();
                consume(TokenType::RightBracket, "expected ']' after index");
                ++indexCount;
            }
            consume(TokenType::Equal, "expected '=' after indexed variable");
            compileExpression();
            emit("STORE_PATH", std::to_string(indexCount), name.line);
            finishSimpleStatement();
            return;
        }

        compileExpression();
        emit("POP", "", previous().line);
        finishSimpleStatement();
    }

    void compileLoadFile(const Token& keyword) {
        if (!loaderLoaded_) {
            throw error(keyword, "load library Loader before loading files");
        }
        const Token& fileToken = consume(TokenType::String,
                                         "expected a quoted file path after 'load file'");
        const std::string requested = decodeString(fileToken);
        std::filesystem::path path;
        try {
            path = loader::canonicalSourcePath(loader::resolveSourcePath(
                requested, keyword.sourceFile));
        } catch (const std::exception& exception) {
            throw error(fileToken, exception.what());
        }
        std::string extension = path.extension().string();
        std::transform(extension.begin(), extension.end(), extension.begin(),
                       [](unsigned char character) {
                           return static_cast<char>(std::tolower(character));
                       });

        if (extension == ".vi") {
            const std::string modulePath = path.u8string();
            if (loadedModules_.find(modulePath) != loadedModules_.end()) {
                finishSimpleStatement();
                return;
            }
            std::string source;
            try {
                source = loader::readSourceFile(path);
            } catch (const std::exception& exception) {
                throw error(fileToken, exception.what());
            }
            Lexer lexer(std::move(source), modulePath);
            std::vector<Token> moduleTokens = lexer.tokenize();
            if (!moduleTokens.empty() && moduleTokens.back().type == TokenType::End) {
                moduleTokens.pop_back();
            }
            finishSimpleStatement();
            loadedModules_.insert(modulePath);
            tokens_.insert(tokens_.begin() + static_cast<std::ptrdiff_t>(position_),
                           std::make_move_iterator(moduleTokens.begin()),
                           std::make_move_iterator(moduleTokens.end()));
            return;
        }

        if (extension != ".py" && extension != ".js") {
            throw error(fileToken, "load file supports .vi, .py, and .js files");
        }
        finishSimpleStatement();
        emit("PUSH_CONST",
             std::to_string(addConstant("string", path.u8string())), keyword.line);
        emit("CALL_LOADER", "load_file 1", keyword.line);
        emit("POP", "", keyword.line);
    }

    TokenType peekType(std::size_t offset) const {
        const std::size_t index = position_ + offset;
        return index < tokens_.size() ? tokens_[index].type : TokenType::End;
    }

    void compileFunction(const Token& keyword) {
        if (inFunctionBody_) {
            throw error(keyword, "nested function definitions are not supported");
        }
        const Token& name = consume(TokenType::Identifier, "expected a function name");
        if (std::find(functionNames_.begin(), functionNames_.end(), name.text) !=
            functionNames_.end()) {
            throw error(name, "function '" + name.text + "' is already defined");
        }
        consume(TokenType::LeftParen, "expected '(' after function name");
        std::vector<std::string> parameters;
        if (!check(TokenType::RightParen)) {
            do {
                const Token& parameter =
                    consume(TokenType::Identifier, "expected a parameter name");
                if (std::find(parameters.begin(), parameters.end(), parameter.text) !=
                    parameters.end()) {
                    throw error(parameter, "duplicate parameter '" + parameter.text + "'");
                }
                parameters.push_back(parameter.text);
            } while (match(TokenType::Comma) && !check(TokenType::RightParen));
        }
        consume(TokenType::RightParen, "expected ')' after function parameters");
        consume(TokenType::Colon, "expected ':' after function signature");

        functionNames_.push_back(name.text);
        const std::size_t skipBody = emit("JUMP", "?", keyword.line);
        std::string metadata = name.text + " " + std::to_string(parameters.size());
        for (const std::string& parameter : parameters) {
            metadata += " " + parameter;
        }
        emit("FUNCTION", std::move(metadata), keyword.line);
        inFunctionBody_ = true;
        compileBlock();
        inFunctionBody_ = false;
        emit("RETURN_VOID", "", keyword.line);
        patchJump(skipBody, instructions_.size());
    }

    void finishSimpleStatement() {
        if (match(TokenType::Semicolon)) {
            return;
        }
        if (match(TokenType::Newline) || check(TokenType::Dedent) || check(TokenType::End)) {
            return;
        }
        throw error(current(), "expected end of line");
    }

    void compileIf(const Token& keyword) {
        compileExpression();
        consume(TokenType::Colon, "expected ':' after condition");
        const std::size_t falseJump = emit("JUMP_IF_FALSE", "?", keyword.line);
        compileBlock();

        if (match(TokenType::Else)) {
            const Token elseKeyword = previous();
            const std::size_t endJump = emit("JUMP", "?", elseKeyword.line);
            patchJump(falseJump, instructions_.size());
            consume(TokenType::Colon, "expected ':' after else");
            compileBlock();
            patchJump(endJump, instructions_.size());
        } else if (match(TokenType::Elif)) {
            const std::size_t endJump = emit("JUMP", "?", previous().line);
            patchJump(falseJump, instructions_.size());
            compileIf(previous());
            patchJump(endJump, instructions_.size());
        } else {
            patchJump(falseJump, instructions_.size());
        }
    }

    void compileWhile(const Token& keyword) {
        const std::size_t loopStart = instructions_.size();
        compileExpression();
        consume(TokenType::Colon, "expected ':' after while condition");
        const std::size_t exitJump = emit("JUMP_IF_FALSE", "?", keyword.line);
        compileBlock();
        emit("JUMP", std::to_string(loopStart), keyword.line);
        patchJump(exitJump, instructions_.size());
    }

    void compileFor(const Token& keyword) {
        const Token& variable =
            consume(TokenType::Identifier, "expected a variable name after 'for'");
        consume(TokenType::In, "expected 'in' after the for-loop variable");
        compileExpression();
        consume(TokenType::Colon, "expected ':' after for-loop iterable");
        emit("ITER_INIT", "", keyword.line);
        const std::size_t loopStart = instructions_.size();
        const std::size_t next = emit("ITER_NEXT", variable.text + " ?",
                                      keyword.line);
        compileBlock();
        emit("JUMP", std::to_string(loopStart), keyword.line);
        const std::size_t iteratorEnd = instructions_.size();
        emit("ITER_END", "", keyword.line);
        instructions_[next].argument =
            variable.text + " " + std::to_string(iteratorEnd);
    }

    void compileTryCatch(const Token& keyword) {
        consume(TokenType::Colon, "expected ':' after 'try'");
        const std::size_t tryBegin = emit("TRY_BEGIN", "?", keyword.line);
        compileBlock();
        emit("TRY_END", "", keyword.line);
        const std::size_t endJump = emit("JUMP", "?", keyword.line);
        if (!match(TokenType::Catch)) {
            throw error(current(), "expected 'catch' after try block");
        }
        const Token catchKeyword = previous();
        std::string errorName = "error";
        if (check(TokenType::Identifier)) {
            errorName = tokens_[position_++].text;
        }
        consume(TokenType::Colon, "expected ':' after 'catch'");
        const std::size_t handler = instructions_.size();
        instructions_[tryBegin].argument =
            std::to_string(handler) + " " + errorName;
        compileBlock();
        patchJump(endJump, instructions_.size());
    }

    void compileBlock() {
        consume(TokenType::Newline, "expected a newline before the block");
        while (match(TokenType::Newline)) {}
        consume(TokenType::Indent, "expected an indented block");
        while (!check(TokenType::Dedent) && !check(TokenType::End)) {
            if (match(TokenType::Newline)) {
                continue;
            }
            compileStatement();
        }
        consume(TokenType::Dedent, "expected the end of the block");
    }

    void compileExpression(int minimumBindingPower = 0) {
        compilePrefix();
        while (true) {
            if (match(TokenType::LeftBracket)) {
                const std::size_t line = previous().line;
                compileExpression();
                consume(TokenType::RightBracket, "expected ']' after index");
                emit("INDEX_GET", "", line);
                continue;
            }
            if (match(TokenType::Dot)) {
                const Token& method = consume(TokenType::Identifier,
                                              "expected a method name after '.'");
                consume(TokenType::LeftParen, "expected '(' after string method name");
                const std::size_t argumentCount = compileCallArguments();
                consume(TokenType::RightParen, "expected ')' after string method arguments");
                emit("CALL_METHOD", method.text + " " +
                                    std::to_string(argumentCount), method.line);
                continue;
            }
            break;
        }
        while (true) {
            const auto binding = infixBinding(current().type);
            if (binding.first < minimumBindingPower) {
                break;
            }
            const Token operation = tokens_[position_++];
            compileExpression(binding.second);
            emit(infixOperation(operation.type), "", operation.line);
        }
    }

    void compilePrefix() {
        const Token token = tokens_[position_++];
        switch (token.type) {
        case TokenType::Integer:
            emit("PUSH_CONST",
                 std::to_string(addConstant("integer", withoutUnderscores(token.text))),
                 token.line);
            return;
        case TokenType::Float:
            emit("PUSH_CONST",
                 std::to_string(addConstant("float", withoutUnderscores(token.text))),
                 token.line);
            return;
        case TokenType::String:
            emit("PUSH_CONST",
                 std::to_string(addConstant("string", decodeString(token))), token.line);
            return;
        case TokenType::True:
            emit("PUSH_CONST", std::to_string(addConstant("bool", "true")), token.line);
            return;
        case TokenType::False:
            emit("PUSH_CONST", std::to_string(addConstant("bool", "false")), token.line);
            return;
        case TokenType::Null:
            emit("PUSH_CONST", std::to_string(addConstant("null", "null")), token.line);
            return;
        case TokenType::LeftBracket: {
            std::size_t count = 0;
            if (!check(TokenType::RightBracket)) {
                do {
                    compileExpression();
                    ++count;
                } while (match(TokenType::Comma) && !check(TokenType::RightBracket));
            }
            consume(TokenType::RightBracket, "expected ']' after list literal");
            emit("MAKE_LIST", std::to_string(count), token.line);
            return;
        }
        case TokenType::LeftBrace: {
            std::size_t count = 0;
            if (!check(TokenType::RightBrace)) {
                do {
                    compileExpression();
                    consume(TokenType::Colon, "expected ':' after dictionary key");
                    compileExpression();
                    ++count;
                } while (match(TokenType::Comma) && !check(TokenType::RightBrace));
            }
            consume(TokenType::RightBrace, "expected '}' after dictionary literal");
            emit("MAKE_DICT", std::to_string(count), token.line);
            return;
        }
        case TokenType::Identifier:
            if (check(TokenType::Increment) || check(TokenType::Decrement)) {
                const bool increment = match(TokenType::Increment);
                if (!increment) consume(TokenType::Decrement, "expected increment operator");
                emit(increment ? "INCREMENT_POST" : "DECREMENT_POST",
                     token.text, token.line);
                return;
            }
            if (token.text == "array" && match(TokenType::LeftBracket)) {
                std::size_t count = 0;
                if (!check(TokenType::RightBracket)) {
                    do {
                        compileExpression();
                        ++count;
                    } while (match(TokenType::Comma) && !check(TokenType::RightBracket));
                }
                consume(TokenType::RightBracket, "expected ']' after array literal");
                emit("MAKE_ARRAY", std::to_string(count), token.line);
                return;
            }
            if (check(TokenType::LeftParen) && isLoaderFunction(token.text)) {
                if (!loaderLoaded_) {
                    throw error(token, "load library loader before calling loader functions");
                }
                ++position_;
                std::size_t argumentCount = 0;
                if (!check(TokenType::RightParen)) {
                    do {
                        compileExpression();
                        ++argumentCount;
                    } while (match(TokenType::Comma) && !check(TokenType::RightParen));
                }
                consume(TokenType::RightParen, "expected ')' after loader arguments");
                emit("CALL_LOADER", token.text + " " + std::to_string(argumentCount),
                     token.line);
                return;
            }
            if (check(TokenType::LeftParen) && isBuiltinFunction(token.text)) {
                ++position_;
                const std::size_t argumentCount = compileCallArguments();
                consume(TokenType::RightParen, "expected ')' after built-in arguments");
                emit("CALL_BUILTIN", token.text + " " +
                                     std::to_string(argumentCount), token.line);
                return;
            }
            if (check(TokenType::LeftParen) && isGpuFunction(token.text)) {
                if (!gpuLoaded_) {
                    throw error(token, "load library gpu before calling graphics functions");
                }
                ++position_;
                std::size_t argumentCount = 0;
                if (!check(TokenType::RightParen)) {
                    do {
                        compileExpression();
                        ++argumentCount;
                    } while (match(TokenType::Comma) && !check(TokenType::RightParen));
                }
                consume(TokenType::RightParen, "expected ')' after GPU arguments");
                emit("CALL_GPU", token.text + " " + std::to_string(argumentCount),
                     token.line);
                return;
            }
            if (token.text == "input" && check(TokenType::LeftParen)) {
                ++position_;
                if (check(TokenType::RightParen)) {
                    throw error(current(), "input expects a prompt string");
                }
                compileExpression();
                consume(TokenType::RightParen, "expected ')' after input prompt");
                emit("INPUT", "", token.line);
                return;
            }
            if (check(TokenType::LeftParen) && isInternetFunction(token.text)) {
                if (!internetLoaded_) {
                    throw error(token, "load library internet before making HTTP requests");
                }
                ++position_;
                std::size_t argumentCount = 0;
                if (!check(TokenType::RightParen)) {
                    do {
                        compileExpression();
                        ++argumentCount;
                    } while (match(TokenType::Comma) && !check(TokenType::RightParen));
                }
                consume(TokenType::RightParen, "expected ')' after internet arguments");
                emit("CALL_INTERNET", token.text + " " + std::to_string(argumentCount),
                     token.line);
                return;
            }
            if (check(TokenType::LeftParen) && isNumbeerFunction(token.text)) {
                if (!numbeerLoaded_) {
                    throw error(token, "load library Numbeer before calling math functions");
                }
                ++position_;
                std::size_t argumentCount = 0;
                if (!check(TokenType::RightParen)) {
                    do {
                        compileExpression();
                        ++argumentCount;
                    } while (match(TokenType::Comma) && !check(TokenType::RightParen));
                }
                consume(TokenType::RightParen, "expected ')' after Numbeer arguments");
                emit("CALL_NUMBEER", token.text + " " + std::to_string(argumentCount),
                     token.line);
                return;
            }
            if (check(TokenType::LeftParen) && isTimeFunction(token.text)) {
                if (!timeLoaded_) {
                    throw error(token, "load library time before calling time functions");
                }
                ++position_;
                std::size_t argumentCount = 0;
                if (!check(TokenType::RightParen)) {
                    do {
                        compileExpression();
                        ++argumentCount;
                    } while (match(TokenType::Comma) && !check(TokenType::RightParen));
                }
                consume(TokenType::RightParen, "expected ')' after time arguments");
                emit("CALL_TIME", token.text + " " + std::to_string(argumentCount),
                     token.line);
                return;
            }
            if ((token.text == "PI" || token.text == "E" || token.text == "TAU") &&
                !numbeerLoaded_) {
                throw error(token, "load library Numbeer before using math constants");
            }
            if (match(TokenType::LeftParen)) {
                const std::size_t argumentCount = compileCallArguments();
                consume(TokenType::RightParen, "expected ')' after function arguments");
                emit("CALL_USER", token.text + " " +
                                  std::to_string(argumentCount), token.line);
                return;
            }
            emit("LOAD", token.text, token.line);
            return;
        case TokenType::Increment:
        case TokenType::Decrement: {
            const Token& variable = consume(TokenType::Identifier,
                                            "prefix increment requires a variable");
            emit(token.type == TokenType::Increment ? "INCREMENT_PRE" : "DECREMENT_PRE",
                 variable.text, token.line);
            return;
        }
        case TokenType::Minus:
            compileExpression(8);
            emit("NEGATE", "", token.line);
            return;
        case TokenType::Plus:
            compileExpression(8);
            return;
        case TokenType::Bang:
        case TokenType::Not:
            compileExpression(8);
            emit("NOT", "", token.line);
            return;
        case TokenType::LeftParen:
            compileExpression();
            consume(TokenType::RightParen, "expected ')' after expression");
            return;
        default:
            throw error(token, "expected an expression");
        }
    }

    std::size_t compileCallArguments() {
        std::size_t count = 0;
        if (!check(TokenType::RightParen)) {
            do {
                compileExpression();
                ++count;
            } while (match(TokenType::Comma) && !check(TokenType::RightParen));
        }
        return count;
    }

    static std::pair<int, int> bindingPower(TokenType type) {
        switch (type) {
        case TokenType::Or: return {1, 2};
        case TokenType::And: return {2, 3};
        case TokenType::EqualEqual:
        case TokenType::BangEqual: return {3, 4};
        case TokenType::Less:
        case TokenType::LessEqual:
        case TokenType::Greater:
        case TokenType::GreaterEqual: return {4, 5};
        case TokenType::Plus:
        case TokenType::Minus: return {5, 6};
        case TokenType::Star:
        case TokenType::Slash:
        case TokenType::FloorSlash:
        case TokenType::Percent: return {6, 7};
        case TokenType::Power: return {8, 8};
        default: return {-1, -1};
        }
    }

    static std::string withoutUnderscores(const std::string& value) {
        std::string result = value;
        result.erase(std::remove(result.begin(), result.end(), '_'), result.end());
        return result;
    }

    static std::string decodeString(const Token& token) {
        std::string result;
        for (std::size_t i = 1; i + 1 < token.text.size(); ++i) {
            if (token.text[i] != '\\') {
                result += token.text[i];
                continue;
            }
            const char escaped = token.text[++i];
            switch (escaped) {
            case 'n': result += '\n'; break;
            case 'r': result += '\r'; break;
            case 't': result += '\t'; break;
            case '0': result += '\0'; break;
            default: result += escaped; break;
            }
        }
        return result;
    }

    static std::pair<int, int> infixBinding(TokenType type) {
        const auto binding = bindingPower(type);
        return binding.first < 0 ? std::pair<int, int>{-1, -1} : binding;
    }

    static std::string infixOperation(TokenType type) {
        switch (type) {
        case TokenType::Or: return "OR";
        case TokenType::And: return "AND";
        case TokenType::EqualEqual: return "COMPARE_EQ";
        case TokenType::BangEqual: return "COMPARE_NE";
        case TokenType::Less: return "COMPARE_LT";
        case TokenType::LessEqual: return "COMPARE_LE";
        case TokenType::Greater: return "COMPARE_GT";
        case TokenType::GreaterEqual: return "COMPARE_GE";
        case TokenType::Plus: return "ADD";
        case TokenType::Minus: return "SUBTRACT";
        case TokenType::Star: return "MULTIPLY";
        case TokenType::Slash: return "DIVIDE";
        case TokenType::FloorSlash: return "FLOOR_DIVIDE";
        case TokenType::Percent: return "MODULO";
        case TokenType::Power: return "POWER";
        default: return "UNKNOWN";
        }
    }

    static bool isNumbeerFunction(const std::string& name) {
        return name == "abs" || name == "sqrt" || name == "sin" || name == "cos" ||
               name == "tan" || name == "asin" || name == "acos" || name == "atan" ||
               name == "atan2" || name == "log" || name == "ln" || name == "log10" ||
               name == "exp" || name == "floor" || name == "ceil" || name == "round" ||
               name == "trunc" || name == "pow" || name == "hypot" || name == "min" ||
               name == "max" || name == "clamp" || name == "radians" ||
               name == "degrees";
    }

    static bool isInternetFunction(const std::string& name) {
        return name == "get" || name == "fetch" || name == "post" ||
               name == "put" || name == "patch" || name == "delete" ||
               name == "del" || name == "head" || name == "download" ||
               name == "status" || name == "response_status" ||
               name == "response_headers" || name == "final_url" ||
               name == "set_timeout" || name == "set_user_agent" ||
               name == "clear_cookies" || name == "request";
    }

    static bool isGpuFunction(const std::string& name) {
        return name == "gpu_input" || name == "input_box" ||
               name == "window" || name == "coordinates" ||
               name == "background" || name == "rect" || name == "rectangle" ||
               name == "rounded_rect" || name == "rounded_rectangle" ||
               name == "circle" || name == "ellipse" || name == "line" ||
               name == "text" || name == "button" || name == "show" ||
               name == "run";
    }

    static bool isTimeFunction(const std::string& name) {
        return name == "time" || name == "time_now" || name == "date" ||
               name == "date_now" || name == "datetime" || name == "timestamp" ||
               name == "sleep" || name == "timer_start" ||
               name == "timer_elapsed" || name == "timer_reset" ||
               name == "timer_stop";
    }

    static bool isLoaderFunction(const std::string& name) {
        return name == "download" || name == "download_file" ||
               name == "bluetooth_send" ||
               name == "bluetooth_receive";
    }

    static bool isBuiltinFunction(const std::string& name) {
        return name == "str" || name == "int" || name == "float" ||
               name == "bool" || name == "list" || name == "array" ||
               name == "dict" || name == "len" || name == "type" ||
               name == "append" || name == "pop" || name == "keys" ||
               name == "values" || name == "range";
    }

    std::vector<Token> tokens_;
    std::size_t position_ = 0;
    std::vector<Instruction> instructions_;
    std::vector<Constant> constants_;
    bool numbeerLoaded_ = false;
    bool internetLoaded_ = false;
    bool gpuLoaded_ = false;
    bool timeLoaded_ = false;
    bool loaderLoaded_ = false;
    bool inFunctionBody_ = false;
    std::vector<std::string> functionNames_;
    std::unordered_set<std::string> loadedModules_;
};

static void writeQuoted(std::ostream& output, const std::string& value) {
    output << '"';
    for (const char c : value) {
        switch (c) {
        case '\0': output << "\\0"; break;
        case '\\': output << "\\\\"; break;
        case '"': output << "\\\""; break;
        case '\n': output << "\\n"; break;
        case '\r': output << "\\r"; break;
        case '\t': output << "\\t"; break;
        default: output << c; break;
        }
    }
    output << '"';
}

static void writeBytecode(std::ostream& output, const Compiler& compiler) {
    output << "VILANG_BYTECODE 1\n\n.constants\n";
    for (std::size_t i = 0; i < compiler.constants().size(); ++i) {
        const Constant& constant = compiler.constants()[i];
        output << "  " << i << ' ' << constant.type << ' ';
        writeQuoted(output, constant.value);
        output << '\n';
    }

    output << "\n.code\n";
    for (std::size_t i = 0; i < compiler.instructions().size(); ++i) {
        const Instruction& instruction = compiler.instructions()[i];
        output << "  " << std::setw(4) << std::setfill('0') << i
               << "  " << std::left << std::setw(16) << std::setfill(' ')
               << instruction.operation << std::right;
        if (!instruction.argument.empty()) {
            output << ' ' << instruction.argument;
        }
        output << "  ; line " << instruction.line << '\n';
    }
}

} // namespace vilang

int main(int argc, char* argv[]) {
    if (argc != 2 && argc != 4) {
        std::cerr << "Usage: vilang-compiler <source.vi> [-o <output.vbc>]\n";
        return 2;
    }
    if (argc == 4 && std::string(argv[2]) != "-o") {
        std::cerr << "Expected -o before the output file\n";
        return 2;
    }

    std::ifstream source(argv[1], std::ios::binary);
    if (!source) {
        std::cerr << "Cannot open source file: " << argv[1] << '\n';
        return 2;
    }
    std::ostringstream sourceBuffer;
    sourceBuffer << source.rdbuf();
    if (source.bad()) {
        std::cerr << "Failed to read source file: " << argv[1] << '\n';
        return 2;
    }
    std::error_code sourcePathError;
    const std::filesystem::path sourcePath =
        std::filesystem::absolute(std::filesystem::path(argv[1]), sourcePathError);
    if (sourcePathError) {
        std::cerr << "Cannot resolve source file path: "
                  << sourcePathError.message() << '\n';
        return 2;
    }

    std::ofstream outputFile;
    std::ostream* output = &std::cout;
    if (argc == 4) {
        outputFile.open(argv[3], std::ios::binary);
        if (!outputFile) {
            std::cerr << "Cannot open output file: " << argv[3] << '\n';
            return 2;
        }
        output = &outputFile;
    }

    try {
        vilang::Lexer lexer(sourceBuffer.str(), sourcePath.u8string());
        vilang::Compiler compiler(lexer.tokenize());
        compiler.compile();
        vilang::writeBytecode(*output, compiler);
        if (!*output) {
            std::cerr << "Failed to write bytecode output\n";
            return 2;
        }
    } catch (const vilang::CompileError& error) {
        std::cerr << "ViLang compiler error: " << error.what() << '\n';
        return 1;
    }

    return 0;
}