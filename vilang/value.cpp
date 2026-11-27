#include <charconv>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

namespace vilang {

using Scalar = std::variant<std::monostate, bool, std::int64_t, double, std::string>;

class Value {
public:
    Value() : data_(std::monostate{}) {}
    explicit Value(bool value) : data_(value) {}
    explicit Value(std::int64_t value) : data_(value) {}
    explicit Value(double value) : data_(value) {}
    explicit Value(std::string value) : data_(std::move(value)) {}

    static Value null() {
        return Value();
    }

    static Value boolean(bool value) {
        return Value(value);
    }

    static Value integer(std::int64_t value) {
        return Value(value);
    }

    static Value floating(double value) {
        return Value(value);
    }

    static Value string(std::string value) {
        return Value(std::move(value));
    }

    bool isNull() const { return std::holds_alternative<std::monostate>(data_); }
    bool isBoolean() const { return std::holds_alternative<bool>(data_); }
    bool isInteger() const { return std::holds_alternative<std::int64_t>(data_); }
    bool isFloat() const { return std::holds_alternative<double>(data_); }
    bool isNumber() const { return isInteger() || isFloat(); }
    bool isString() const { return std::holds_alternative<std::string>(data_); }

    bool asBoolean() const {
        if (!isBoolean()) {
            throw std::runtime_error("value is not a boolean");
        }
        return std::get<bool>(data_);
    }

    std::int64_t asInteger() const {
        if (!isInteger()) {
            throw std::runtime_error("value is not an integer");
        }
        return std::get<std::int64_t>(data_);
    }

    double asFloat() const {
        if (isFloat()) {
            return std::get<double>(data_);
        }
        if (isInteger()) {
            return static_cast<double>(std::get<std::int64_t>(data_));
        }
        throw std::runtime_error("value is not a number");
    }

    long double asNumber() const {
        if (isInteger()) {
            return static_cast<long double>(std::get<std::int64_t>(data_));
        }
        if (isFloat()) {
            return static_cast<long double>(std::get<double>(data_));
        }
        throw std::runtime_error("value is not a number");
    }

    const std::string& asString() const {
        if (!isString()) {
            throw std::runtime_error("value is not a string");
        }
        return std::get<std::string>(data_);
    }

    bool truthy() const {
        if (isNull()) return false;
        if (isBoolean()) return asBoolean();
        if (isInteger()) return asInteger() != 0;
        if (isFloat()) return std::get<double>(data_) != 0.0;
        return !asString().empty();
    }

    std::string typeName() const {
        if (isNull()) return "null";
        if (isBoolean()) return "bool";
        if (isInteger()) return "int";
        if (isFloat()) return "float";
        return "string";
    }

    std::string toString() const {
        if (isNull()) return "null";
        if (isBoolean()) return asBoolean() ? "true" : "false";
        if (isInteger()) return std::to_string(asInteger());
        if (isFloat()) {
            std::ostringstream output;
            output << std::setprecision(std::numeric_limits<double>::max_digits10)
                   << std::get<double>(data_);
            return output.str();
        }
        return asString();
    }

    bool equals(const Value& other) const {
        if (isNumber() && other.isNumber()) {
            return asNumber() == other.asNumber();
        }
        if (data_.index() != other.data_.index()) {
            return false;
        }
        return data_ == other.data_;
    }

private:
    Scalar data_;
};

class VariableError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct Variable {
    Value value;
    bool isConstant = false;
};

class Scope {
public:
    bool contains(const std::string& name) const {
        return variables_.find(name) != variables_.end();
    }

    void define(const std::string& name, Value value, bool isConstant = false) {
        if (name.empty()) {
            throw VariableError("variable name cannot be empty");
        }
        if (!isValidName(name)) {
            throw VariableError("invalid variable name '" + name + "'");
        }
        if (contains(name)) {
            throw VariableError("variable '" + name + "' is already defined");
        }
        variables_.emplace(name, Variable{std::move(value), isConstant});
    }

    const Variable& get(const std::string& name) const {
        const auto found = variables_.find(name);
        if (found == variables_.end()) {
            throw VariableError("variable '" + name + "' is not defined");
        }
        return found->second;
    }

    Variable& getMutable(const std::string& name) {
        auto found = variables_.find(name);
        if (found == variables_.end()) {
            throw VariableError("variable '" + name + "' is not defined");
        }
        return found->second;
    }

    void assign(const std::string& name, Value value) {
        Variable& variable = getMutable(name);
        if (variable.isConstant) {
            throw VariableError("cannot assign to constant '" + name + "'");
        }
        variable.value = std::move(value);
    }

    const std::unordered_map<std::string, Variable>& variables() const {
        return variables_;
    }

    static bool isValidName(const std::string& name) {
        if (name.empty()) return false;
        const unsigned char first = static_cast<unsigned char>(name.front());
        if (!((first >= 'a' && first <= 'z') ||
              (first >= 'A' && first <= 'Z') || first == '_')) {
            return false;
        }
        for (unsigned char character : name) {
            if (!((character >= 'a' && character <= 'z') ||
                  (character >= 'A' && character <= 'Z') ||
                  (character >= '0' && character <= '9') || character == '_')) {
                return false;
            }
        }
        return true;
    }

private:
    std::unordered_map<std::string, Variable> variables_;
};

class VariableStore {
public:
    VariableStore() {
        scopes_.emplace_back();
    }

    void pushScope() {
        scopes_.emplace_back();
    }

    void popScope() {
        if (scopes_.size() <= 1) {
            throw VariableError("cannot remove the global scope");
        }
        scopes_.pop_back();
    }

    std::size_t scopeCount() const {
        return scopes_.size();
    }

    void define(const std::string& name, Value value, bool isConstant = false) {
        scopes_.back().define(name, std::move(value), isConstant);
    }

    void assign(const std::string& name, Value value) {
        for (std::size_t i = scopes_.size(); i > 0; --i) {
            Scope& scope = scopes_[i - 1];
            if (scope.contains(name)) {
                scope.assign(name, std::move(value));
                return;
            }
        }
        throw VariableError("undefined variable '" + name + "'");
    }

    const Variable& get(const std::string& name) const {
        for (std::size_t i = scopes_.size(); i > 0; --i) {
            const Scope& scope = scopes_[i - 1];
            if (scope.contains(name)) {
                return scope.get(name);
            }
        }
        throw VariableError("undefined variable '" + name + "'");
    }

    bool contains(const std::string& name) const {
        for (std::size_t i = scopes_.size(); i > 0; --i) {
            if (scopes_[i - 1].contains(name)) {
                return true;
            }
        }
        return false;
    }

private:
    std::vector<Scope> scopes_;
};

static std::string trim(const std::string& text) {
    const std::size_t first = text.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const std::size_t last = text.find_last_not_of(" \t\r\n");
    return text.substr(first, last - first + 1);
}

static bool parseInteger(const std::string& text, std::int64_t& value) {
    if (text.empty()) return false;
    const char* begin = text.data();
    const char* end = begin + text.size();
    const auto result = std::from_chars(begin, end, value);
    return result.ec == std::errc{} && result.ptr == end;
}

static bool parseFloat(const std::string& text, double& value) {
    try {
        std::size_t parsed = 0;
        value = std::stod(text, &parsed);
        return parsed == text.size();
    } catch (const std::exception&) {
        return false;
    }
}

static Value parseLiteral(const std::string& input) {
    const std::string text = trim(input);
    if (text == "true") return Value::boolean(true);
    if (text == "false") return Value::boolean(false);
    if (text == "null") return Value::null();

    if (text.size() >= 2 &&
        ((text.front() == '"' && text.back() == '"') ||
         (text.front() == '\'' && text.back() == '\''))) {
        return Value::string(text.substr(1, text.size() - 2));
    }

    std::int64_t integer = 0;
    if (parseInteger(text, integer)) {
        return Value::integer(integer);
    }

    double floating = 0.0;
    if (parseFloat(text, floating)) {
        return Value::floating(floating);
    }
    return Value::string(text);
}

static void printUsage() {
    std::cout
        << "ViLang variable demo\n"
        << "Commands:\n"
        << "  let <name> = <value>\n"
        << "  const <name> = <value>\n"
        << "  <name> = <value>\n"
        << "  get <name>\n"
        << "  push\n"
        << "  pop\n"
        << "  quit\n";
}

static bool executeCommand(const std::string& line, VariableStore& store) {
    const std::string command = trim(line);
    if (command.empty()) return true;
    if (command == "quit" || command == "exit") return false;
    if (command == "help") {
        printUsage();
        return true;
    }
    if (command == "push") {
        store.pushScope();
        std::cout << "Scope " << store.scopeCount() << " entered\n";
        return true;
    }
    if (command == "pop") {
        store.popScope();
        std::cout << "Scope " << store.scopeCount() << " active\n";
        return true;
    }
    if (command.rfind("get ", 0) == 0) {
        const std::string name = trim(command.substr(4));
        const Variable& variable = store.get(name);
        std::cout << variable.value.toString()
                  << " [" << variable.value.typeName() << ']';
        if (variable.isConstant) std::cout << " const";
        std::cout << '\n';
        return true;
    }

    std::istringstream stream(command);
    std::string declaration;
    stream >> declaration;

    bool isConstant = false;
    if (declaration == "let") {
        isConstant = false;
    } else if (declaration == "const") {
        isConstant = true;
    } else if (declaration == "get" || declaration == "push" ||
               declaration == "pop" || declaration == "help") {
        throw VariableError("invalid command");
    } else {
        const std::size_t equal = command.find('=');
        if (equal == std::string::npos) {
            throw VariableError("expected '=' in assignment");
        }
        const std::string name = trim(command.substr(0, equal));
        if (!Scope::isValidName(name)) {
            throw VariableError("invalid variable name '" + name + "'");
        }
        store.assign(name, parseLiteral(command.substr(equal + 1)));
        std::cout << name << " = " << store.get(name).value.toString() << '\n';
        return true;
    }

    std::string name;
    stream >> name;
    std::string remainder;
    std::getline(stream, remainder);
    remainder = trim(remainder);
    if (remainder.empty() || remainder.front() != '=') {
        throw VariableError("expected '=' after variable name");
    }
    const Value value = parseLiteral(remainder.substr(1));
    store.define(name, value, isConstant);
    std::cout << name << " = " << value.toString()
              << " [" << value.typeName() << ']';
    if (isConstant) std::cout << " const";
    std::cout << '\n';
    return true;
}

} // namespace vilang

int main(int argc, char* argv[]) {
    if (argc > 2) {
        std::cerr << "Usage: vilang-value [script-file]\n";
        return 2;
    }

    vilang::VariableStore store;
    if (argc == 2) {
        std::ifstream input(argv[1]);
        if (!input) {
            std::cerr << "Cannot open variable script: " << argv[1] << '\n';
            return 2;
        }
        std::string line;
        std::size_t lineNumber = 0;
        try {
            while (std::getline(input, line)) {
                ++lineNumber;
                if (lineNumber > 0 && vilang::trim(line).empty()) {
                    continue;
                }
                vilang::executeCommand(line, store);
            }
        } catch (const vilang::VariableError& error) {
            std::cerr << "ViLang variable error at line " << lineNumber
                      << ": " << error.what() << '\n';
            return 1;
        }
        return 0;
    }

    vilang::printUsage();
    std::string line;
    while (std::cout << "> " && std::getline(std::cin, line)) {
        try {
            if (!vilang::executeCommand(line, store)) {
                break;
            }
        } catch (const vilang::VariableError& error) {
            std::cerr << "ViLang variable error: " << error.what() << '\n';
        }
    }
    return 0;
}