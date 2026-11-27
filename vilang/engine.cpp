#include <charconv>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <variant>
#include <vector>
#include <algorithm>

#include "num.cpp"
#include "net.cpp"

namespace vilang {

struct ListData;
struct ArrayData;
struct DictData;
using Value = std::variant<std::monostate, bool, std::int64_t, double, std::string,
                           std::shared_ptr<ListData>, std::shared_ptr<ArrayData>,
                           std::shared_ptr<DictData>>;

struct ListData {
    std::vector<Value> values;
};

struct ArrayData {
    std::vector<Value> values;
};

struct DictData {
    std::map<std::string, Value> values;
};

} // namespace vilang

#include "time.cpp"
#include "load.cpp"
#include "gpu.cpp"

namespace vilang {

struct Constant {
    std::string type;
    std::string text;
};

struct Instruction {
    std::string operation;
    std::string argument;
    std::size_t line;
};

struct Program {
    std::vector<Constant> constants;
    std::vector<Instruction> instructions;
};

class EngineError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

static std::string trim(const std::string& value) {
    const std::size_t first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return "";
    }
    const std::size_t last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

static bool parseUnsigned(const std::string& text, std::size_t& value) {
    if (text.empty()) {
        return false;
    }
    const char* begin = text.data();
    const char* end = begin + text.size();
    const auto result = std::from_chars(begin, end, value);
    return result.ec == std::errc{} && result.ptr == end;
}

static std::string readQuoted(const std::string& text, std::size_t& position,
                              const std::string& context) {
    while (position < text.size() && (text[position] == ' ' || text[position] == '\t')) {
        ++position;
    }
    if (position == text.size() || text[position] != '"') {
        throw EngineError(context + ": expected a quoted value");
    }

    ++position;
    std::string value;
    bool closed = false;
    while (position < text.size()) {
        const char c = text[position++];
        if (c == '"') {
            closed = true;
            break;
        }
        if (c != '\\') {
            value += c;
            continue;
        }
        if (position == text.size()) {
            throw EngineError(context + ": incomplete escape sequence");
        }
        switch (text[position++]) {
        case '0': value += '\0'; break;
        case 'n': value += '\n'; break;
        case 'r': value += '\r'; break;
        case 't': value += '\t'; break;
        case '\\': value += '\\'; break;
        case '"': value += '"'; break;
        default: throw EngineError(context + ": unsupported escape sequence");
        }
    }
    if (!closed) {
        throw EngineError(context + ": unterminated quoted value");
    }
    if (!trim(text.substr(position)).empty()) {
        throw EngineError(context + ": unexpected text after quoted value");
    }
    return value;
}

static Program loadProgram(std::istream& input) {
    Program program;
    std::string line;
    std::size_t lineNumber = 0;
    std::size_t expectedIndex = 0;
    enum class Section { None, Constants, Code };
    Section section = Section::None;
    bool hasHeader = false;
    bool hasConstants = false;
    bool hasCode = false;

    while (std::getline(input, line)) {
        ++lineNumber;
        const std::string content = trim(line);
        if (content.empty()) {
            continue;
        }
        if (!hasHeader) {
            if (content != "VILANG_BYTECODE 1") {
                throw EngineError("line " + std::to_string(lineNumber) +
                                  ": expected VILANG_BYTECODE 1 header");
            }
            hasHeader = true;
            continue;
        }
        if (content == ".constants") {
            if (hasConstants || section == Section::Code) {
                throw EngineError("line " + std::to_string(lineNumber) +
                                  ": unexpected .constants section");
            }
            hasConstants = true;
            section = Section::Constants;
            expectedIndex = 0;
            continue;
        }
        if (content == ".code") {
            if (hasCode) {
                throw EngineError("line " + std::to_string(lineNumber) +
                                  ": duplicate .code section");
            }
            hasCode = true;
            section = Section::Code;
            expectedIndex = 0;
            continue;
        }

        const std::size_t comment = content.find(';');
        const std::string body = trim(content.substr(0, comment));
        if (body.empty()) {
            continue;
        }

        std::istringstream fields(body);
        std::string indexText;
        std::string kind;
        std::string value;
        if (!(fields >> indexText >> kind)) {
            throw EngineError("line " + std::to_string(lineNumber) +
                              ": malformed bytecode entry");
        }
        std::size_t index = 0;
        if (!parseUnsigned(indexText, index) || index != expectedIndex) {
            throw EngineError("line " + std::to_string(lineNumber) +
                              ": bytecode indices must be consecutive starting at 0");
        }

        if (section == Section::Constants) {
            std::string remainder;
            std::getline(fields, remainder);
            std::size_t position = 0;
            value = readQuoted(remainder, position, "line " + std::to_string(lineNumber));
            program.constants.push_back({kind, std::move(value)});
        } else if (section == Section::Code) {
            std::string argument;
            std::getline(fields, argument);
            std::size_t sourceLine = lineNumber;
            if (comment != std::string::npos) {
                std::istringstream metadata(trim(content.substr(comment + 1)));
                std::string label;
                std::size_t annotatedLine = 0;
                if (metadata >> label && label == "line") {
                    if (!(metadata >> annotatedLine) || annotatedLine == 0) {
                        throw EngineError("line " + std::to_string(lineNumber) +
                                          ": invalid source line annotation");
                    }
                    sourceLine = annotatedLine;
                }
            }
            program.instructions.push_back({kind, trim(argument), sourceLine});
        } else {
            throw EngineError("line " + std::to_string(lineNumber) +
                              ": bytecode entry is outside a section");
        }
        ++expectedIndex;
    }

    if (input.bad()) {
        throw EngineError("failed to read bytecode input");
    }
    if (!hasHeader || !hasConstants || !hasCode) {
        throw EngineError("bytecode must contain a header, .constants, and .code sections");
    }
    if (program.instructions.empty()) {
        throw EngineError("bytecode contains no instructions");
    }
    return program;
}

static bool isNumber(const Value& value) {
    return std::holds_alternative<std::int64_t>(value) ||
           std::holds_alternative<double>(value);
}

static long double asNumber(const Value& value) {
    if (const auto* integer = std::get_if<std::int64_t>(&value)) {
        return static_cast<long double>(*integer);
    }
    if (const auto* number = std::get_if<double>(&value)) {
        return static_cast<long double>(*number);
    }
    throw EngineError("expected a number");
}

static bool isIntegral(const Value& value) {
    return std::holds_alternative<std::int64_t>(value);
}

static double asDouble(const Value& value) {
    if (const auto* integer = std::get_if<std::int64_t>(&value)) {
        return static_cast<double>(*integer);
    }
    if (const auto* number = std::get_if<double>(&value)) {
        return *number;
    }
    throw EngineError("expected a number");
}

static std::int64_t checkedInteger(long double value, const std::string& operation) {
    constexpr long double minimum = -9223372036854775808.0L;
    constexpr long double maximumExclusive = 9223372036854775808.0L;
    if (!std::isfinite(value) || value < minimum || value >= maximumExclusive) {
        throw EngineError(operation + " result is outside the integer range");
    }
    return static_cast<std::int64_t>(value);
}

static bool isTruthy(const Value& value) {
    if (std::holds_alternative<std::monostate>(value)) return false;
    if (const auto* boolean = std::get_if<bool>(&value)) return *boolean;
    if (const auto* integer = std::get_if<std::int64_t>(&value)) return *integer != 0;
    if (const auto* number = std::get_if<double>(&value)) return *number != 0.0;
    if (const auto* text = std::get_if<std::string>(&value)) return !text->empty();
    if (const auto* list = std::get_if<std::shared_ptr<ListData>>(&value)) {
        return !(*list)->values.empty();
    }
    if (const auto* array = std::get_if<std::shared_ptr<ArrayData>>(&value)) {
        return !(*array)->values.empty();
    }
    return !std::get<std::shared_ptr<DictData>>(value)->values.empty();
}

static std::string display(const Value& value, std::size_t depth = 0) {
    if (depth >= 32) return "...";
    if (std::holds_alternative<std::monostate>(value)) return "null";
    if (const auto* boolean = std::get_if<bool>(&value)) {
        return *boolean ? "true" : "false";
    }
    if (const auto* integer = std::get_if<std::int64_t>(&value)) {
        return std::to_string(*integer);
    }
    if (const auto* number = std::get_if<double>(&value)) {
        std::ostringstream output;
        output << std::setprecision(std::numeric_limits<double>::max_digits10) << *number;
        return output.str();
    }
    if (const auto* text = std::get_if<std::string>(&value)) return *text;
    std::ostringstream output;
    if (const auto* list = std::get_if<std::shared_ptr<ListData>>(&value)) {
        output << '[';
        for (std::size_t i = 0; i < (*list)->values.size(); ++i) {
            if (i != 0) output << ", ";
            output << display((*list)->values[i], depth + 1);
        }
        output << ']';
        return output.str();
    }
    if (const auto* array = std::get_if<std::shared_ptr<ArrayData>>(&value)) {
        output << "array[";
        for (std::size_t i = 0; i < (*array)->values.size(); ++i) {
            if (i != 0) output << ", ";
            output << display((*array)->values[i], depth + 1);
        }
        output << ']';
        return output.str();
    }
    const auto& dictionary = std::get<std::shared_ptr<DictData>>(value)->values;
    output << '{';
    std::size_t index = 0;
    for (const auto& entry : dictionary) {
        if (index++ != 0) output << ", ";
        output << '"' << entry.first << "\": "
               << display(entry.second, depth + 1);
    }
    output << '}';
    return output.str();
}

static bool valuesEqual(const Value& left, const Value& right,
                        std::size_t depth = 0) {
    if (depth >= 64) return false;
    if (isNumber(left) && isNumber(right)) {
        return asNumber(left) == asNumber(right);
    }
    if (left.index() != right.index()) {
        return false;
    }
    if (const auto* leftList = std::get_if<std::shared_ptr<ListData>>(&left)) {
        const auto& rightPointer = std::get<std::shared_ptr<ListData>>(right);
        if (*leftList == rightPointer) return true;
        const auto& rightList = rightPointer->values;
        const auto& leftValues = (*leftList)->values;
        if (leftValues.size() != rightList.size()) return false;
        for (std::size_t i = 0; i < leftValues.size(); ++i) {
            if (!valuesEqual(leftValues[i], rightList[i], depth + 1)) return false;
        }
        return true;
    }
    if (const auto* leftArray = std::get_if<std::shared_ptr<ArrayData>>(&left)) {
        const auto& rightPointer = std::get<std::shared_ptr<ArrayData>>(right);
        if (*leftArray == rightPointer) return true;
        const auto& rightArray = rightPointer->values;
        const auto& leftValues = (*leftArray)->values;
        if (leftValues.size() != rightArray.size()) return false;
        for (std::size_t i = 0; i < leftValues.size(); ++i) {
            if (!valuesEqual(leftValues[i], rightArray[i], depth + 1)) return false;
        }
        return true;
    }
    if (const auto* leftDict = std::get_if<std::shared_ptr<DictData>>(&left)) {
        const auto& rightPointer = std::get<std::shared_ptr<DictData>>(right);
        if (*leftDict == rightPointer) return true;
        const auto& rightDict = rightPointer->values;
        if ((*leftDict)->values.size() != rightDict.size()) return false;
        for (const auto& entry : (*leftDict)->values) {
            const auto found = rightDict.find(entry.first);
            if (found == rightDict.end() ||
                !valuesEqual(entry.second, found->second, depth + 1)) {
                return false;
            }
        }
        return true;
    }
    return left == right;
}

static std::vector<Value> parseConstants(const std::vector<Constant>& constants);

class VirtualMachine {
public:
    VirtualMachine(Program program, std::istream& input, std::ostream& output)
        : program_(std::move(program)), input_(input), output_(output),
          constants_(parseConstants(program_.constants)) {
        registerFunctions();
    }

    void run() {
        while (instructionPointer_ < program_.instructions.size()) {
            const std::size_t current = instructionPointer_++;
            const Instruction& instruction = program_.instructions[current];
            try {
                execute(instruction);
            } catch (const EngineError& error) {
                const std::string message =
                    "line " + std::to_string(instruction.line) +
                    " (" + instruction.operation + "): " + error.what();
                if (!handleRuntimeError(message)) throw EngineError(message);
            }
        }
    }

private:
    struct Variable {
        Value value;
        bool isConstant;
    };

    struct FunctionInfo {
        std::size_t entry;
        std::vector<std::string> parameters;
    };

    struct CallFrame {
        std::size_t returnAddress;
        std::size_t stackBase;
        std::size_t iteratorBase;
        std::size_t handlerBase;
        std::map<std::string, Variable> locals;
    };

    struct IteratorFrame {
        std::vector<Value> values;
        std::size_t position = 0;
    };

    struct ExceptionHandler {
        std::size_t target;
        std::size_t stackDepth;
        std::size_t frameDepth;
        std::size_t iteratorDepth;
        std::string errorName;
    };

    Value pop() {
        if (stack_.empty()) {
            throw EngineError("stack underflow");
        }
        Value result = std::move(stack_.back());
        stack_.pop_back();
        return result;
    }

    Value& peek() {
        if (stack_.empty()) {
            throw EngineError("stack underflow");
        }
        return stack_.back();
    }

    void registerFunctions() {
        for (std::size_t i = 0; i < program_.instructions.size(); ++i) {
            const Instruction& instruction = program_.instructions[i];
            if (instruction.operation != "FUNCTION") continue;
            std::istringstream fields(instruction.argument);
            std::string name;
            std::string countText;
            std::size_t count = 0;
            if (!(fields >> name >> countText) || !parseUnsigned(countText, count)) {
                throw EngineError("malformed FUNCTION instruction");
            }
            FunctionInfo function{i + 1, {}};
            function.parameters.reserve(count);
            for (std::size_t parameter = 0; parameter < count; ++parameter) {
                std::string parameterName;
                if (!(fields >> parameterName)) {
                    throw EngineError("malformed FUNCTION parameters");
                }
                function.parameters.push_back(std::move(parameterName));
            }
            std::string trailing;
            if (name.empty() || fields >> trailing ||
                functions_.find(name) != functions_.end()) {
                throw EngineError("invalid or duplicate function definition '" + name + "'");
            }
            functions_.emplace(std::move(name), std::move(function));
        }
    }

    std::map<std::string, Variable>& activeVariables() {
        return frames_.empty() ? variables_ : frames_.back().locals;
    }

    const Value& constantAt(const std::string& argument) const {
        std::size_t index = 0;
        if (!parseUnsigned(argument, index) || index >= constants_.size()) {
            throw EngineError("invalid constant index '" + argument + "'");
        }
        return constants_[index];
    }

    std::size_t jumpTarget(const Instruction& instruction) const {
        std::size_t target = 0;
        if (!parseUnsigned(instruction.argument, target) ||
            target >= program_.instructions.size()) {
            throw EngineError("invalid jump target '" + instruction.argument + "'");
        }
        return target;
    }

    static std::size_t parseInstructionCount(const std::string& argument,
                                             const std::string& operation) {
        std::size_t count = 0;
        if (!parseUnsigned(argument, count)) {
            throw EngineError("malformed " + operation + " instruction");
        }
        return count;
    }

    static std::size_t normalizeIndex(const Value& index, std::size_t size,
                                     const std::string& operation) {
        const auto* integer = std::get_if<std::int64_t>(&index);
        if (integer == nullptr) {
            throw EngineError(operation + " index must be an integer");
        }
        const long double normalized = *integer < 0
                                           ? static_cast<long double>(size) + *integer
                                           : static_cast<long double>(*integer);
        if (normalized < 0.0L || normalized >= static_cast<long double>(size)) {
            throw EngineError(operation + " index is out of range");
        }
        return static_cast<std::size_t>(normalized);
    }

    static Value getIndex(const Value& collection, const Value& index) {
        if (const auto* list = std::get_if<std::shared_ptr<ListData>>(&collection)) {
            return (*list)->values[normalizeIndex(index, (*list)->values.size(), "list")];
        }
        if (const auto* array = std::get_if<std::shared_ptr<ArrayData>>(&collection)) {
            return (*array)->values[normalizeIndex(index, (*array)->values.size(), "array")];
        }
        if (const auto* dictionary =
                std::get_if<std::shared_ptr<DictData>>(&collection)) {
            const auto* key = std::get_if<std::string>(&index);
            if (key == nullptr) throw EngineError("dictionary key must be a string");
            const auto found = (*dictionary)->values.find(*key);
            if (found == (*dictionary)->values.end()) {
                throw EngineError("dictionary key '" + *key + "' does not exist");
            }
            return found->second;
        }
        if (const auto* text = std::get_if<std::string>(&collection)) {
            const std::vector<std::string> characters = splitUtf8(*text);
            return characters[normalizeIndex(index, characters.size(), "string")];
        }
        throw EngineError("value does not support indexed access");
    }

    static void setIndex(const Value& collection, const Value& index,
                         const Value& value) {
        if (const auto* list = std::get_if<std::shared_ptr<ListData>>(&collection)) {
            (*list)->values[normalizeIndex(index, (*list)->values.size(), "list")] = value;
            return;
        }
        if (const auto* array = std::get_if<std::shared_ptr<ArrayData>>(&collection)) {
            (*array)->values[normalizeIndex(index, (*array)->values.size(), "array")] = value;
            return;
        }
        if (const auto* dictionary =
                std::get_if<std::shared_ptr<DictData>>(&collection)) {
            const auto* key = std::get_if<std::string>(&index);
            if (key == nullptr) throw EngineError("dictionary key must be a string");
            (*dictionary)->values[*key] = value;
            return;
        }
        throw EngineError("indexed assignment requires a list, array, or dictionary");
    }

    static std::vector<std::string> splitUtf8(const std::string& text) {
        std::vector<std::string> characters;
        for (std::size_t i = 0; i < text.size();) {
            const unsigned char first = static_cast<unsigned char>(text[i]);
            std::size_t length = first < 0x80 ? 1
                                 : (first & 0xE0) == 0xC0 ? 2
                                 : (first & 0xF0) == 0xE0 ? 3
                                 : (first & 0xF8) == 0xF0 ? 4 : 1;
            if (i + length > text.size()) length = 1;
            for (std::size_t j = 1; j < length; ++j) {
                if ((static_cast<unsigned char>(text[i + j]) & 0xC0) != 0x80) {
                    length = 1;
                    break;
                }
            }
            characters.push_back(text.substr(i, length));
            i += length;
        }
        return characters;
    }

    static std::vector<Value> iterableValues(const Value& value,
                                             const std::string& operation) {
        if (const auto* list = std::get_if<std::shared_ptr<ListData>>(&value)) {
            return (*list)->values;
        }
        if (const auto* array = std::get_if<std::shared_ptr<ArrayData>>(&value)) {
            return (*array)->values;
        }
        if (const auto* text = std::get_if<std::string>(&value)) {
            std::vector<Value> result;
            for (std::string& character : splitUtf8(*text)) {
                result.emplace_back(std::move(character));
            }
            return result;
        }
        if (const auto* dictionary = std::get_if<std::shared_ptr<DictData>>(&value)) {
            std::vector<Value> result;
            result.reserve((*dictionary)->values.size());
            for (const auto& entry : (*dictionary)->values) {
                result.emplace_back(entry.first);
            }
            return result;
        }
        throw EngineError(operation + " expects a list, array, dictionary, or string");
    }

    void callBuiltin(const std::string& argument) {
        std::istringstream fields(argument);
        std::string name;
        std::string countText;
        std::string trailing;
        std::size_t count = 0;
        if (!(fields >> name >> countText) || fields >> trailing ||
            !parseUnsigned(countText, count) || count > stack_.size()) {
            throw EngineError("malformed built-in call");
        }
        std::vector<Value> arguments(count);
        for (std::size_t i = count; i > 0; --i) arguments[i - 1] = pop();

        if (name == "range") {
            if (count < 1 || count > 3) {
                throw EngineError("range expects stop, start/stop, or start/stop/step");
            }
            std::int64_t start = 0;
            std::int64_t stop = 0;
            std::int64_t step = 1;
            if (count == 1) {
                const auto* end = std::get_if<std::int64_t>(&arguments[0]);
                if (end == nullptr) throw EngineError("range arguments must be integers");
                stop = *end;
            } else {
                const auto* begin = std::get_if<std::int64_t>(&arguments[0]);
                const auto* end = std::get_if<std::int64_t>(&arguments[1]);
                if (begin == nullptr || end == nullptr) {
                    throw EngineError("range arguments must be integers");
                }
                start = *begin;
                stop = *end;
                if (count == 3) {
                    const auto* stride = std::get_if<std::int64_t>(&arguments[2]);
                    if (stride == nullptr) {
                        throw EngineError("range arguments must be integers");
                    }
                    step = *stride;
                }
            }
            if (step == 0) throw EngineError("range step cannot be zero");
            auto result = std::make_shared<ListData>();
            constexpr std::size_t maximumRangeSize = 1000000;
            for (std::int64_t value = start;
                 step > 0 ? value < stop : value > stop;) {
                if (result->values.size() >= maximumRangeSize) {
                    throw EngineError("range exceeds the 1000000 element limit");
                }
                result->values.emplace_back(value);
                const long double next = static_cast<long double>(value) + step;
                if ((step > 0 && next >= stop) || (step < 0 && next <= stop)) break;
                value = checkedInteger(next, "range");
            }
            stack_.emplace_back(std::move(result));
        } else if (name == "str") {
            if (count != 1) throw EngineError("str expects 1 argument");
            stack_.emplace_back(display(arguments[0]));
        } else if (name == "int" || name == "float") {
            if (count != 1) throw EngineError(name + " expects 1 argument");
            if (name == "int") {
                if (const auto* integer = std::get_if<std::int64_t>(&arguments[0])) {
                    stack_.emplace_back(*integer);
                } else if (const auto* number = std::get_if<double>(&arguments[0])) {
                    stack_.emplace_back(checkedInteger(std::trunc(*number), "int"));
                } else if (const auto* boolean = std::get_if<bool>(&arguments[0])) {
                    stack_.emplace_back(static_cast<std::int64_t>(*boolean));
                } else if (const auto* text = std::get_if<std::string>(&arguments[0])) {
                    const std::string value = trim(*text);
                    std::int64_t converted = 0;
                    const auto parsed = std::from_chars(
                        value.data(), value.data() + value.size(), converted);
                    if (value.empty() || parsed.ec != std::errc{} ||
                        parsed.ptr != value.data() + value.size()) {
                        throw EngineError("int cannot convert '" + *text + "'");
                    }
                    stack_.emplace_back(converted);
                } else {
                    throw EngineError("int expects a number, boolean, or integer string");
                }
            } else {
                double converted = 0.0;
                if (isNumber(arguments[0])) {
                    converted = asDouble(arguments[0]);
                } else if (const auto* boolean = std::get_if<bool>(&arguments[0])) {
                    converted = *boolean ? 1.0 : 0.0;
                } else if (const auto* text = std::get_if<std::string>(&arguments[0])) {
                    const std::string value = trim(*text);
                    std::size_t parsed = 0;
                    try {
                        converted = std::stod(value, &parsed);
                    } catch (const std::exception&) {
                        throw EngineError("float cannot convert '" + *text + "'");
                    }
                    if (parsed != value.size() || !std::isfinite(converted)) {
                        throw EngineError("float cannot convert '" + *text + "'");
                    }
                } else {
                    throw EngineError("float expects a number, boolean, or numeric string");
                }
                stack_.emplace_back(converted);
            }
        } else if (name == "bool") {
            if (count != 1) throw EngineError("bool expects 1 argument");
            stack_.emplace_back(isTruthy(arguments[0]));
        } else if (name == "len") {
            if (count != 1) throw EngineError("len expects 1 argument");
            std::size_t size = 0;
            if (const auto* text = std::get_if<std::string>(&arguments[0])) {
                size = splitUtf8(*text).size();
            } else if (const auto* list =
                           std::get_if<std::shared_ptr<ListData>>(&arguments[0])) {
                size = (*list)->values.size();
            } else if (const auto* array =
                           std::get_if<std::shared_ptr<ArrayData>>(&arguments[0])) {
                size = (*array)->values.size();
            } else if (const auto* dictionary =
                           std::get_if<std::shared_ptr<DictData>>(&arguments[0])) {
                size = (*dictionary)->values.size();
            } else {
                throw EngineError("len expects a string, list, array, or dictionary");
            }
            if (size > static_cast<std::size_t>(
                           std::numeric_limits<std::int64_t>::max())) {
                throw EngineError("container is too large for len");
            }
            stack_.emplace_back(static_cast<std::int64_t>(size));
        } else if (name == "type") {
            if (count != 1) throw EngineError("type expects 1 argument");
            const Value& value = arguments[0];
            const char* type = std::holds_alternative<std::monostate>(value) ? "null"
                               : std::holds_alternative<bool>(value) ? "bool"
                               : std::holds_alternative<std::int64_t>(value) ? "int"
                               : std::holds_alternative<double>(value) ? "float"
                               : std::holds_alternative<std::string>(value) ? "str"
                               : std::holds_alternative<std::shared_ptr<ListData>>(value)
                                     ? "list"
                               : std::holds_alternative<std::shared_ptr<ArrayData>>(value)
                                     ? "array"
                                     : "dict";
            stack_.emplace_back(type);
        } else if (name == "list" || name == "array") {
            if (count > 1) throw EngineError(name + " expects 0 or 1 argument");
            std::vector<Value> values;
            if (count == 1) values = iterableValues(arguments[0], name);
            if (name == "list") {
                stack_.emplace_back(std::make_shared<ListData>(ListData{std::move(values)}));
            } else {
                stack_.emplace_back(std::make_shared<ArrayData>(ArrayData{std::move(values)}));
            }
        } else if (name == "dict") {
            if (count > 1) throw EngineError("dict expects 0 or 1 argument");
            auto dictionary = std::make_shared<DictData>();
            if (count == 1) {
                if (const auto* source =
                        std::get_if<std::shared_ptr<DictData>>(&arguments[0])) {
                    dictionary->values = (*source)->values;
                } else {
                    const std::vector<Value> entries =
                        iterableValues(arguments[0], "dict");
                    for (const Value& entry : entries) {
                        std::vector<Value> pair;
                        if (const auto* list =
                                std::get_if<std::shared_ptr<ListData>>(&entry)) {
                            pair = (*list)->values;
                        } else if (const auto* array =
                                       std::get_if<std::shared_ptr<ArrayData>>(&entry)) {
                            pair = (*array)->values;
                        } else {
                            throw EngineError("dict expects key-value pairs");
                        }
                        if (pair.size() != 2) {
                            throw EngineError("each dict entry must contain exactly 2 values");
                        }
                        const auto* key = std::get_if<std::string>(&pair[0]);
                        if (key == nullptr) {
                            throw EngineError("dictionary keys must be strings");
                        }
                        dictionary->values[*key] = pair[1];
                    }
                }
            }
            stack_.emplace_back(std::move(dictionary));
        } else if (name == "append") {
            if (count != 2) throw EngineError("append expects a list and a value");
            const auto* list = std::get_if<std::shared_ptr<ListData>>(&arguments[0]);
            if (list == nullptr) throw EngineError("append can only grow a list");
            (*list)->values.push_back(arguments[1]);
            stack_.push_back(arguments[0]);
        } else if (name == "pop") {
            if (count < 1 || count > 2) throw EngineError("pop expects a list and optional index");
            const auto* list = std::get_if<std::shared_ptr<ListData>>(&arguments[0]);
            if (list == nullptr) throw EngineError("pop expects a list");
            if ((*list)->values.empty()) throw EngineError("pop from an empty list");
            const Value index = count == 2
                                    ? arguments[1]
                                    : Value(static_cast<std::int64_t>(
                                          (*list)->values.size() - 1));
            const std::size_t position =
                normalizeIndex(index, (*list)->values.size(), "list");
            Value result = std::move((*list)->values[position]);
            (*list)->values.erase((*list)->values.begin() +
                                  static_cast<std::ptrdiff_t>(position));
            stack_.push_back(std::move(result));
        } else if (name == "keys" || name == "values") {
            if (count != 1) throw EngineError(name + " expects a dictionary");
            const auto* dictionary =
                std::get_if<std::shared_ptr<DictData>>(&arguments[0]);
            if (dictionary == nullptr) throw EngineError(name + " expects a dictionary");
            auto result = std::make_shared<ListData>();
            for (const auto& entry : (*dictionary)->values) {
                result->values.push_back(name == "keys" ? Value(entry.first)
                                                         : entry.second);
            }
            stack_.emplace_back(std::move(result));
        } else {
            throw EngineError("unknown built-in '" + name + "'");
        }
    }

    void callMethod(const std::string& argument) {
        std::istringstream fields(argument);
        std::string method;
        std::string countText;
        std::string trailing;
        std::size_t count = 0;
        if (!(fields >> method >> countText) || fields >> trailing ||
            !parseUnsigned(countText, count) || count + 1 > stack_.size()) {
            throw EngineError("malformed string method call");
        }
        std::vector<Value> arguments(count);
        for (std::size_t i = count; i > 0; --i) arguments[i - 1] = pop();
        const Value receiver = pop();
        const auto* text = std::get_if<std::string>(&receiver);
        if (text == nullptr) {
            throw EngineError("string methods can only be called on strings");
        }

        if (method == "upper" || method == "lower" || method == "capitalize") {
            if (count != 0) throw EngineError(method + " expects no arguments");
            std::string result = *text;
            for (char& character : result) {
                const unsigned char value = static_cast<unsigned char>(character);
                if (method == "upper") character = static_cast<char>(std::toupper(value));
                else if (method == "lower") character = static_cast<char>(std::tolower(value));
            }
            if (method == "capitalize" && !result.empty()) {
                result[0] = static_cast<char>(
                    std::toupper(static_cast<unsigned char>(result[0])));
                for (std::size_t i = 1; i < result.size(); ++i) {
                    result[i] = static_cast<char>(
                        std::tolower(static_cast<unsigned char>(result[i])));
                }
            }
            stack_.emplace_back(std::move(result));
        } else if (method == "strip" || method == "lstrip" || method == "rstrip") {
            if (count != 0) throw EngineError(method + " expects no arguments");
            const auto whitespace = [](unsigned char character) {
                return std::isspace(character) != 0;
            };
            std::size_t begin = 0;
            std::size_t end = text->size();
            if (method != "rstrip") {
                while (begin < end && whitespace(
                           static_cast<unsigned char>((*text)[begin]))) ++begin;
            }
            if (method != "lstrip") {
                while (end > begin && whitespace(
                           static_cast<unsigned char>((*text)[end - 1]))) --end;
            }
            stack_.emplace_back(text->substr(begin, end - begin));
        } else if (method == "startswith" || method == "endswith" ||
                   method == "contains" || method == "find") {
            if (count != 1 || !std::get_if<std::string>(&arguments[0])) {
                throw EngineError(method + " expects one string argument");
            }
            const std::string& needle = std::get<std::string>(arguments[0]);
            if (method == "startswith") {
                stack_.emplace_back(text->rfind(needle, 0) == 0);
            } else if (method == "endswith") {
                stack_.emplace_back(needle.size() <= text->size() &&
                                    text->compare(text->size() - needle.size(),
                                                  needle.size(), needle) == 0);
            } else {
                const std::size_t position = text->find(needle);
                if (method == "contains") {
                    stack_.emplace_back(position != std::string::npos);
                } else {
                    stack_.emplace_back(position == std::string::npos
                                            ? std::int64_t{-1}
                                            : checkedInteger(position, "find"));
                }
            }
        } else if (method == "replace") {
            if (count != 2 || !std::get_if<std::string>(&arguments[0]) ||
                !std::get_if<std::string>(&arguments[1])) {
                throw EngineError("replace expects old and new strings");
            }
            const std::string& oldText = std::get<std::string>(arguments[0]);
            const std::string& newText = std::get<std::string>(arguments[1]);
            if (oldText.empty()) throw EngineError("replace search string cannot be empty");
            std::string result = *text;
            std::size_t position = 0;
            while ((position = result.find(oldText, position)) != std::string::npos) {
                result.replace(position, oldText.size(), newText);
                position += newText.size();
            }
            stack_.emplace_back(std::move(result));
        } else if (method == "split") {
            if (count > 1 || (count == 1 && !std::get_if<std::string>(&arguments[0]))) {
                throw EngineError("split expects an optional string separator");
            }
            auto result = std::make_shared<ListData>();
            if (count == 0) {
                std::istringstream words(*text);
                std::string word;
                while (words >> word) result->values.emplace_back(std::move(word));
            } else {
                const std::string& separator = std::get<std::string>(arguments[0]);
                if (separator.empty()) {
                    throw EngineError("split separator cannot be empty");
                }
                std::size_t begin = 0;
                for (;;) {
                    const std::size_t position = text->find(separator, begin);
                    if (position == std::string::npos) {
                        result->values.emplace_back(text->substr(begin));
                        break;
                    }
                    result->values.emplace_back(text->substr(begin, position - begin));
                    begin = position + separator.size();
                }
            }
            stack_.emplace_back(std::move(result));
        } else if (method == "join") {
            if (count != 1) throw EngineError("join expects one iterable argument");
            const std::vector<Value> values = iterableValues(arguments[0], "join");
            std::string result;
            for (std::size_t i = 0; i < values.size(); ++i) {
                const auto* item = std::get_if<std::string>(&values[i]);
                if (item == nullptr) throw EngineError("join items must be strings");
                if (i != 0) result += *text;
                result += *item;
            }
            stack_.emplace_back(std::move(result));
        } else {
            throw EngineError("unknown string method '" + method + "'");
        }
    }

    void callUser(const std::string& argument) {
        std::istringstream fields(argument);
        std::string name;
        std::string countText;
        std::string trailing;
        std::size_t count = 0;
        if (!(fields >> name >> countText) || fields >> trailing ||
            !parseUnsigned(countText, count) || count > stack_.size()) {
            throw EngineError("malformed function call");
        }
        const auto function = functions_.find(name);
        if (function == functions_.end()) {
            throw EngineError("undefined function '" + name + "'");
        }
        if (count != function->second.parameters.size()) {
            throw EngineError("function '" + name + "' expects " +
                              std::to_string(function->second.parameters.size()) +
                              " arguments, got " + std::to_string(count));
        }
        if (frames_.size() >= 1024) {
            throw EngineError("maximum function call depth exceeded");
        }
        std::vector<Value> arguments(count);
        for (std::size_t i = count; i > 0; --i) arguments[i - 1] = pop();

        CallFrame frame{instructionPointer_, stack_.size(), iterators_.size(),
                    handlers_.size(), {}};
        for (std::size_t i = 0; i < count; ++i) {
            frame.locals.emplace(function->second.parameters[i],
                                 Variable{std::move(arguments[i]), false});
        }
        frames_.push_back(std::move(frame));
        instructionPointer_ = function->second.entry;
    }

    void updateVariable(const std::string& name, const Value& value) {
        std::map<std::string, Variable>* scope = &variables_;
        if (!frames_.empty()) {
            const auto local = frames_.back().locals.find(name);
            if (local != frames_.back().locals.end()) {
                if (local->second.isConstant) {
                    throw EngineError("cannot assign to constant '" + name + "'");
                }
                local->second.value = value;
                return;
            }
            scope = &frames_.back().locals;
        }
        const auto existing = scope->find(name);
        if (existing != scope->end()) {
            if (existing->second.isConstant) {
                throw EngineError("cannot assign to constant '" + name + "'");
            }
            existing->second.value = value;
        } else {
            scope->emplace(name, Variable{value, false});
        }
    }

    void incrementVariable(const std::string& name, bool increment, bool prefix) {
        std::map<std::string, Variable>* scope = &variables_;
        if (!frames_.empty()) {
            const auto local = frames_.back().locals.find(name);
            if (local != frames_.back().locals.end()) {
                scope = &frames_.back().locals;
            }
        }
        auto variable = scope->find(name);
        if (variable == scope->end()) {
            throw EngineError("undefined variable '" + name + "'");
        }
        if (variable->second.isConstant) {
            throw EngineError("cannot assign to constant '" + name + "'");
        }
        Value previous = variable->second.value;
        if (const auto* integer = std::get_if<std::int64_t>(&previous)) {
            variable->second.value = checkedInteger(
                static_cast<long double>(*integer) + (increment ? 1.0L : -1.0L),
                increment ? "increment" : "decrement");
        } else if (const auto* number = std::get_if<double>(&previous)) {
            const double next = *number + (increment ? 1.0 : -1.0);
            if (!std::isfinite(next)) throw EngineError("increment result is not finite");
            variable->second.value = next;
        } else {
            throw EngineError("increment and decrement require a numeric variable");
        }
        stack_.push_back(prefix ? variable->second.value : std::move(previous));
    }

    bool handleRuntimeError(const std::string& message) {
        if (handlers_.empty()) return false;
        const ExceptionHandler handler = std::move(handlers_.back());
        handlers_.pop_back();
        if (handler.frameDepth > frames_.size() ||
            handler.iteratorDepth > iterators_.size() ||
            handler.stackDepth > stack_.size()) {
            throw EngineError("invalid exception-handler state");
        }
        frames_.resize(handler.frameDepth);
        iterators_.resize(handler.iteratorDepth);
        stack_.resize(handler.stackDepth);
        auto& scope = activeVariables();
        const auto existing = scope.find(handler.errorName);
        if (existing != scope.end()) {
            if (existing->second.isConstant) {
                throw EngineError("cannot bind error to constant '" +
                                  handler.errorName + "'");
            }
            existing->second.value = message;
        } else {
            scope.emplace(handler.errorName, Variable{message, false});
        }
        instructionPointer_ = handler.target;
        return true;
    }

    void returnFromFunction(Value result) {
        if (frames_.empty()) {
            halted_ = true;
            return;
        }
        const CallFrame frame = std::move(frames_.back());
        frames_.pop_back();
        iterators_.resize(frame.iteratorBase);
        handlers_.resize(frame.handlerBase);
        stack_.resize(frame.stackBase);
        stack_.push_back(std::move(result));
        instructionPointer_ = frame.returnAddress;
    }

    void execute(const Instruction& instruction) {
        const std::string& op = instruction.operation;
        const std::string& argument = instruction.argument;

        if (op == "PUSH_CONST") {
            stack_.push_back(constantAt(argument));
        } else if (op == "LOAD") {
            if (!frames_.empty()) {
                const auto local = frames_.back().locals.find(argument);
                if (local != frames_.back().locals.end()) {
                    stack_.push_back(local->second.value);
                    return;
                }
            }
            const auto global = variables_.find(argument);
            if (global == variables_.end()) {
                throw EngineError("undefined variable '" + argument + "'");
            }
            stack_.push_back(global->second.value);
        } else if (op == "DEFINE_VAR" || op == "DEFINE_CONST") {
            Value value = pop();
            auto& scope = activeVariables();
            if (scope.find(argument) != scope.end()) {
                throw EngineError("variable '" + argument + "' is already defined");
            }
            scope.emplace(argument, Variable{std::move(value), op == "DEFINE_CONST"});
        } else if (op == "STORE") {
            Value value = pop();
            std::map<std::string, Variable>* scope = &variables_;
            if (!frames_.empty() &&
                frames_.back().locals.find(argument) != frames_.back().locals.end()) {
                scope = &frames_.back().locals;
            }
            const auto variable = scope->find(argument);
            if (variable == scope->end()) {
                throw EngineError("undefined variable '" + argument + "'");
            }
            if (variable->second.isConstant) {
                throw EngineError("cannot assign to constant '" + argument + "'");
            }
            variable->second.value = std::move(value);
        } else if (op == "INCREMENT_PRE" || op == "INCREMENT_POST" ||
                   op == "DECREMENT_PRE" || op == "DECREMENT_POST") {
            incrementVariable(argument,
                              op == "INCREMENT_PRE" || op == "INCREMENT_POST",
                              op == "INCREMENT_PRE" || op == "DECREMENT_PRE");
        } else if (op == "ITER_INIT") {
            const Value iterable = pop();
            iterators_.push_back({iterableValues(iterable, "for"), 0});
        } else if (op == "ITER_NEXT") {
            std::istringstream fields(argument);
            std::string variable;
            std::string targetText;
            std::string trailing;
            std::size_t target = 0;
            if (!(fields >> variable >> targetText) || fields >> trailing ||
                !parseUnsigned(targetText, target) ||
                target >= program_.instructions.size() || iterators_.empty()) {
                throw EngineError("malformed iterator instruction");
            }
            IteratorFrame& iterator = iterators_.back();
            if (iterator.position >= iterator.values.size()) {
                instructionPointer_ = target;
            } else {
                updateVariable(variable, iterator.values[iterator.position++]);
            }
        } else if (op == "ITER_END") {
            if (iterators_.empty()) throw EngineError("iterator stack underflow");
            iterators_.pop_back();
        } else if (op == "TRY_BEGIN") {
            std::istringstream fields(argument);
            std::string targetText;
            std::string errorName;
            std::string trailing;
            std::size_t target = 0;
            if (!(fields >> targetText >> errorName) || fields >> trailing ||
                !parseUnsigned(targetText, target) ||
                target >= program_.instructions.size()) {
                throw EngineError("malformed TRY_BEGIN instruction");
            }
            handlers_.push_back({target, stack_.size(), frames_.size(),
                                 iterators_.size(), errorName});
        } else if (op == "TRY_END") {
            if (handlers_.empty()) throw EngineError("exception handler stack underflow");
            handlers_.pop_back();
        } else if (op == "MAKE_LIST" || op == "MAKE_ARRAY") {
            const std::size_t count = parseInstructionCount(argument, op);
            if (count > stack_.size()) throw EngineError("stack underflow");
            std::vector<Value> values(count);
            for (std::size_t i = count; i > 0; --i) values[i - 1] = pop();
            if (op == "MAKE_LIST") {
                stack_.emplace_back(std::make_shared<ListData>(ListData{std::move(values)}));
            } else {
                stack_.emplace_back(std::make_shared<ArrayData>(ArrayData{std::move(values)}));
            }
        } else if (op == "MAKE_DICT") {
            const std::size_t count = parseInstructionCount(argument, op);
            if (count > stack_.size() / 2) throw EngineError("stack underflow");
            std::vector<std::pair<std::string, Value>> entries;
            entries.reserve(count);
            for (std::size_t i = 0; i < count; ++i) {
                Value value = pop();
                Value key = pop();
                const auto* stringKey = std::get_if<std::string>(&key);
                if (stringKey == nullptr) {
                    throw EngineError("dictionary keys must be strings");
                }
                entries.emplace_back(*stringKey, std::move(value));
            }
            auto dictionary = std::make_shared<DictData>();
            for (auto entry = entries.rbegin(); entry != entries.rend(); ++entry) {
                dictionary->values[entry->first] = std::move(entry->second);
            }
            stack_.emplace_back(std::move(dictionary));
        } else if (op == "INDEX_GET") {
            const Value index = pop();
            const Value collection = pop();
            stack_.push_back(getIndex(collection, index));
        } else if (op == "STORE_INDEX" || op == "STORE_PATH") {
            const Value value = pop();
            const std::size_t count = op == "STORE_INDEX"
                                          ? 1
                                          : parseInstructionCount(argument, op);
            if (count == 0 || count > stack_.size()) {
                throw EngineError("invalid indexed assignment path");
            }
            std::vector<Value> indices(count);
            for (std::size_t i = count; i > 0; --i) indices[i - 1] = pop();
            Value collection = pop();
            for (std::size_t i = 0; i + 1 < count; ++i) {
                collection = getIndex(collection, indices[i]);
            }
            setIndex(collection, indices.back(), value);
        } else if (op == "CALL_BUILTIN") {
            callBuiltin(argument);
        } else if (op == "CALL_METHOD") {
            callMethod(argument);
        } else if (op == "CALL_USER") {
            callUser(argument);
        } else if (op == "FUNCTION") {
        } else if (op == "LOAD_LIBRARY") {
            loadLibrary(argument);
        } else if (op == "CALL_NUMBEER") {
            callNumbeer(argument);
        } else if (op == "CALL_INTERNET") {
            callInternet(argument);
        } else if (op == "CALL_GPU") {
            callGpu(argument);
        } else if (op == "CALL_TIME") {
            callTime(argument);
        } else if (op == "CALL_LOADER") {
            callLoader(argument);
        } else if (op == "POP") {
            pop();
        } else if (op == "PRINT") {
            output_ << display(pop()) << '\n';
            if (!output_) throw EngineError("failed to write program output");
        } else if (op == "INPUT") {
            const Value prompt = pop();
            const auto* text = std::get_if<std::string>(&prompt);
            if (text == nullptr) {
                throw EngineError("input prompt must be a string");
            }
            output_ << *text << std::flush;
            if (!output_) throw EngineError("failed to write input prompt");
            std::string answer;
            if (!std::getline(input_, answer)) {
                throw EngineError("failed to read input");
            }
            stack_.emplace_back(std::move(answer));
        } else if (op == "JUMP") {
            instructionPointer_ = jumpTarget(instruction);
        } else if (op == "JUMP_IF_FALSE") {
            if (!isTruthy(pop())) instructionPointer_ = jumpTarget(instruction);
        } else if (op == "ADD" || op == "SUBTRACT" || op == "MULTIPLY" ||
                   op == "DIVIDE" || op == "FLOOR_DIVIDE" || op == "MODULO" ||
                   op == "POWER") {
            executeArithmetic(op);
        } else if (op == "NEGATE") {
            Value value = pop();
            if (!isNumber(value)) throw EngineError("unary '-' expects a number");
            if (isIntegral(value)) {
                const std::int64_t integer = std::get<std::int64_t>(value);
                if (integer == std::numeric_limits<std::int64_t>::min()) {
                    throw EngineError("integer negation overflow");
                }
                stack_.emplace_back(-integer);
            } else {
                stack_.emplace_back(-std::get<double>(value));
            }
        } else if (op == "NOT") {
            stack_.emplace_back(!isTruthy(pop()));
        } else if (op == "AND" || op == "OR") {
            const Value right = pop();
            const Value left = pop();
            stack_.emplace_back(op == "AND"
                                    ? isTruthy(left) && isTruthy(right)
                                    : isTruthy(left) || isTruthy(right));
        } else if (op == "COMPARE_EQ" || op == "COMPARE_NE") {
            const Value right = pop();
            const Value left = pop();
            const bool equal = valuesEqual(left, right);
            stack_.emplace_back(op == "COMPARE_EQ" ? equal : !equal);
        } else if (op == "COMPARE_LT" || op == "COMPARE_LE" ||
                   op == "COMPARE_GT" || op == "COMPARE_GE") {
            executeComparison(op);
        } else if (op == "RETURN") {
            returnFromFunction(pop());
        } else if (op == "RETURN_VOID") {
            returnFromFunction(std::monostate{});
        } else if (op == "HALT") {
            halted_ = true;
        } else if (op == "NOP") {
        } else {
            throw EngineError("unknown instruction '" + op + "'");
        }

        if (halted_) {
            instructionPointer_ = program_.instructions.size();
        }
    }

    void executeArithmetic(const std::string& op) {
        const Value right = pop();
        const Value left = pop();

        if (op == "ADD" && std::holds_alternative<std::string>(left) &&
            std::holds_alternative<std::string>(right)) {
            stack_.emplace_back(std::get<std::string>(left) + std::get<std::string>(right));
            return;
        }
        if (op == "ADD" &&
            std::holds_alternative<std::shared_ptr<ListData>>(left) &&
            std::holds_alternative<std::shared_ptr<ListData>>(right)) {
            std::vector<Value> values =
                std::get<std::shared_ptr<ListData>>(left)->values;
            const auto& rightValues =
                std::get<std::shared_ptr<ListData>>(right)->values;
            values.insert(values.end(), rightValues.begin(), rightValues.end());
            stack_.emplace_back(std::make_shared<ListData>(ListData{std::move(values)}));
            return;
        }
        if (op == "ADD" &&
            std::holds_alternative<std::shared_ptr<ArrayData>>(left) &&
            std::holds_alternative<std::shared_ptr<ArrayData>>(right)) {
            std::vector<Value> values =
                std::get<std::shared_ptr<ArrayData>>(left)->values;
            const auto& rightValues =
                std::get<std::shared_ptr<ArrayData>>(right)->values;
            values.insert(values.end(), rightValues.begin(), rightValues.end());
            stack_.emplace_back(std::make_shared<ArrayData>(ArrayData{std::move(values)}));
            return;
        }
        if (!isNumber(left) || !isNumber(right)) {
            throw EngineError(op + " expects two numbers" +
                              (op == "ADD" ? ", two strings, two lists, or two arrays"
                                           : ""));
        }

        if (op == "DIVIDE") {
            const double divisor = asDouble(right);
            if (divisor == 0.0) throw EngineError("division by zero");
            stack_.emplace_back(asDouble(left) / divisor);
            return;
        }
        if (op == "FLOOR_DIVIDE" || op == "MODULO") {
            if (isIntegral(left) && isIntegral(right)) {
                const std::int64_t dividend = std::get<std::int64_t>(left);
                const std::int64_t divisor = std::get<std::int64_t>(right);
                if (divisor == 0) throw EngineError("division by zero");
                if (dividend == std::numeric_limits<std::int64_t>::min() && divisor == -1) {
                    if (op == "FLOOR_DIVIDE") {
                        throw EngineError("integer division overflow");
                    }
                    stack_.emplace_back(std::int64_t{0});
                    return;
                }
                std::int64_t quotient = dividend / divisor;
                std::int64_t remainder = dividend % divisor;
                if (remainder != 0 && ((dividend < 0) != (divisor < 0))) {
                    --quotient;
                    remainder += divisor;
                }
                stack_.emplace_back(op == "FLOOR_DIVIDE" ? quotient : remainder);
                return;
            }
            const long double divisor = asNumber(right);
            if (divisor == 0.0L) throw EngineError("division by zero");
            const long double quotient = std::floor(asNumber(left) / divisor);
            if (op == "FLOOR_DIVIDE") {
                stack_.emplace_back(static_cast<double>(quotient));
            } else {
                stack_.emplace_back(static_cast<double>(asNumber(left) - quotient * divisor));
            }
            return;
        }
        if (op == "POWER") {
            const double result = std::pow(asDouble(left), asDouble(right));
            if (!std::isfinite(result)) throw EngineError("power result is not finite");
            stack_.emplace_back(result);
            return;
        }

        const long double leftNumber = asNumber(left);
        const long double rightNumber = asNumber(right);
        const long double result = op == "ADD" ? leftNumber + rightNumber
                                    : op == "SUBTRACT" ? leftNumber - rightNumber
                                                       : leftNumber * rightNumber;
        if (isIntegral(left) && isIntegral(right)) {
            stack_.emplace_back(checkedInteger(result, op));
        } else {
            const double floatingResult = static_cast<double>(result);
            if (!std::isfinite(floatingResult)) throw EngineError(op + " result is not finite");
            stack_.emplace_back(floatingResult);
        }
    }

    void loadLibrary(const std::string& name) {
        if (name == "loader") {
            loaderLoaded_ = true;
            return;
        }
        if (name == "time") {
            timeLoaded_ = true;
            return;
        }
        if (name == "gpu") {
            gpuLoaded_ = true;
            return;
        }
        if (name == "internet") {
            internetLoaded_ = true;
            return;
        }
        if (name != "Numbeer") {
            throw EngineError("unknown library '" + name + "'");
        }
        if (numbeerLoaded_) {
            return;
        }

        const double pi = std::acos(-1.0);
        if (variables_.find("PI") != variables_.end() ||
            variables_.find("E") != variables_.end() ||
            variables_.find("TAU") != variables_.end()) {
            throw EngineError("Numbeer constants conflict with existing variables");
        }
        variables_.emplace("PI", Variable{pi, true});
        variables_.emplace("E", Variable{std::exp(1.0), true});
        variables_.emplace("TAU", Variable{2.0 * pi, true});
        numbeerLoaded_ = true;
    }

    void callTime(const std::string& argument) {
        if (!timeLoaded_) {
            throw EngineError("time library is not loaded");
        }
        std::istringstream fields(argument);
        std::string function;
        std::string countText;
        std::string trailing;
        std::size_t count = 0;
        if (!(fields >> function >> countText) || fields >> trailing ||
            !parseUnsigned(countText, count) || count > stack_.size()) {
            throw EngineError("malformed time library call");
        }

        std::vector<Value> arguments(count);
        for (std::size_t i = count; i > 0; --i) {
            arguments[i - 1] = pop();
        }

        try {
            stack_.push_back(time::call(function, arguments));
        } catch (const std::exception& error) {
            throw EngineError(error.what());
        }
    }

    void callLoader(const std::string& argument) {
        if (!loaderLoaded_) {
            throw EngineError("loader library is not loaded");
        }
        std::istringstream fields(argument);
        std::string function;
        std::string countText;
        std::string trailing;
        std::size_t count = 0;
        if (!(fields >> function >> countText) || fields >> trailing ||
            !parseUnsigned(countText, count) || count > stack_.size()) {
            throw EngineError("malformed loader library call");
        }

        std::vector<Value> arguments(count);
        for (std::size_t i = count; i > 0; --i) {
            arguments[i - 1] = pop();
        }

        try {
            stack_.push_back(loader::call(function, arguments, input_, output_));
        } catch (const std::exception& error) {
            throw EngineError(error.what());
        }
    }

    void callNumbeer(const std::string& argument) {
        if (!numbeerLoaded_) {
            throw EngineError("Numbeer library is not loaded");
        }
        std::istringstream fields(argument);
        std::string function;
        std::string countText;
        std::string trailing;
        std::size_t count = 0;
        if (!(fields >> function >> countText) || fields >> trailing ||
            !parseUnsigned(countText, count)) {
            throw EngineError("malformed Numbeer call");
        }
        if (count > stack_.size()) {
            throw EngineError("stack underflow in Numbeer call");
        }

        std::vector<double> arguments(count);
        for (std::size_t i = count; i > 0; --i) {
            const Value value = pop();
            if (!isNumber(value)) {
                throw EngineError(function + " expects numeric arguments");
            }
            arguments[i - 1] = asDouble(value);
        }
        try {
            stack_.emplace_back(numbeer::call(function, arguments));
        } catch (const std::exception& error) {
            throw EngineError(error.what());
        }
    }

    void callInternet(const std::string& argument) {
        if (!internetLoaded_) {
            throw EngineError("internet library is not loaded");
        }
        std::istringstream fields(argument);
        std::string function;
        std::string countText;
        std::string trailing;
        std::size_t count = 0;
        if (!(fields >> function >> countText) || fields >> trailing ||
            !parseUnsigned(countText, count) || count > stack_.size()) {
            throw EngineError("malformed internet library call");
        }

        std::vector<Value> arguments(count);
        for (std::size_t i = count; i > 0; --i) {
            arguments[i - 1] = pop();
        }

        try {
            if (function == "get" || function == "fetch") {
                if (count != 1 || !std::get_if<std::string>(&arguments[0])) {
                    throw EngineError(function + " expects a URL string");
                }
                const internet::Response response =
                    internet::get(std::get<std::string>(arguments[0]));
                stack_.emplace_back(response.body);
            } else if (function == "post" || function == "put" ||
                       function == "patch" || function == "delete" ||
                       function == "del") {
                if (count < 2 || count > 3 ||
                    !std::get_if<std::string>(&arguments[0]) ||
                    !std::get_if<std::string>(&arguments[1]) ||
                    (count == 3 && !std::get_if<std::string>(&arguments[2]))) {
                    throw EngineError(function + " expects a URL, body, and optional headers");
                }
                const std::string& url = std::get<std::string>(arguments[0]);
                const std::string& body = std::get<std::string>(arguments[1]);
                const std::string headers = count == 3
                                                ? std::get<std::string>(arguments[2])
                                                : "";
                internet::Response response;
                if (function == "post") response = internet::post(url, body, headers);
                else if (function == "put") response = internet::put(url, body, headers);
                else if (function == "patch") response = internet::patch(url, body, headers);
                else response = internet::remove(url, body, headers);
                stack_.emplace_back(response.body);
            } else if (function == "head" || function == "headers") {
                if (count != 1 || !std::get_if<std::string>(&arguments[0])) {
                    throw EngineError(function + " expects a URL string");
                }
                if (function == "head") {
                    stack_.emplace_back(internet::head(std::get<std::string>(arguments[0])).headers);
                } else {
                    stack_.emplace_back(internet::headers(std::get<std::string>(arguments[0])));
                }
            } else if (function == "status") {
                if (count != 1 || !std::get_if<std::string>(&arguments[0])) {
                    throw EngineError("status expects a URL string");
                }
                stack_.emplace_back(static_cast<std::int64_t>(
                    internet::status(std::get<std::string>(arguments[0]))));
            } else if (function == "download") {
                if (count != 2 ||
                    !std::get_if<std::string>(&arguments[0]) ||
                    !std::get_if<std::string>(&arguments[1])) {
                    throw EngineError("download expects a URL and output path");
                }
                internet::download(std::get<std::string>(arguments[0]),
                                   std::get<std::string>(arguments[1]));
                stack_.emplace_back(true);
            } else if (function == "set_timeout") {
                if (count != 1 || !std::holds_alternative<std::int64_t>(arguments[0])) {
                    throw EngineError("set_timeout expects milliseconds");
                }
                const std::int64_t milliseconds = std::get<std::int64_t>(arguments[0]);
                if (milliseconds < 1000 || milliseconds > 300000) {
                    throw EngineError("timeout must be between 1000 and 300000 ms");
                }
                internet::setTimeout(static_cast<DWORD>(milliseconds));
                stack_.emplace_back(true);
            } else if (function == "set_user_agent") {
                if (count != 1 || !std::get_if<std::string>(&arguments[0])) {
                    throw EngineError("set_user_agent expects a string");
                }
                internet::setUserAgent(std::get<std::string>(arguments[0]));
                stack_.emplace_back(true);
            } else if (function == "clear_cookies") {
                if (count != 0) throw EngineError("clear_cookies expects no arguments");
                internet::clearCookies();
                stack_.emplace_back(true);
            } else if (function == "response_status") {
                if (count != 0) throw EngineError("response_status expects no arguments");
                stack_.emplace_back(static_cast<std::int64_t>(
                    internet::responseStatus()));
            } else if (function == "response_headers") {
                if (count != 0) throw EngineError("response_headers expects no arguments");
                stack_.emplace_back(internet::responseHeaders());
            } else if (function == "final_url") {
                if (count != 0) throw EngineError("final_url expects no arguments");
                stack_.emplace_back(internet::finalUrl());
            } else if (function == "request") {
                if (count < 2 || count > 4 ||
                    !std::get_if<std::string>(&arguments[0]) ||
                    !std::get_if<std::string>(&arguments[1]) ||
                    (count >= 3 && !std::get_if<std::string>(&arguments[2])) ||
                    (count == 4 && !std::get_if<std::string>(&arguments[3]))) {
                    throw EngineError("request expects method, URL, optional body and headers");
                }
                const std::string& method = std::get<std::string>(arguments[0]);
                const std::string& url = std::get<std::string>(arguments[1]);
                const std::string& body = count >= 3
                                              ? std::get<std::string>(arguments[2])
                                              : "";
                const std::string& headers = count == 4
                                                 ? std::get<std::string>(arguments[3])
                                                 : "";
                stack_.emplace_back(internet::request(method, url, body, headers).body);
            } else {
                throw EngineError("unknown internet function '" + function + "'");
            }
        } catch (const std::exception& error) {
            throw EngineError(error.what());
        }
    }

    void callGpu(const std::string& argument) {
        if (!gpuLoaded_) {
            throw EngineError("gpu library is not loaded");
        }
        std::istringstream fields(argument);
        std::string function;
        std::string countText;
        std::string trailing;
        std::size_t count = 0;
        if (!(fields >> function >> countText) || fields >> trailing ||
            !parseUnsigned(countText, count) || count > stack_.size()) {
            throw EngineError("malformed GPU library call");
        }

        std::vector<Value> arguments(count);
        for (std::size_t i = count; i > 0; --i) {
            arguments[i - 1] = pop();
        }
        std::vector<gpu::Argument> gpuArguments;
        gpuArguments.reserve(arguments.size());
        for (const Value& value : arguments) {
            if (const auto* boolean = std::get_if<bool>(&value)) {
                gpuArguments.emplace_back(*boolean);
            } else if (const auto* integer = std::get_if<std::int64_t>(&value)) {
                gpuArguments.emplace_back(*integer);
            } else if (const auto* number = std::get_if<double>(&value)) {
                gpuArguments.emplace_back(*number);
            } else if (const auto* text = std::get_if<std::string>(&value)) {
                gpuArguments.emplace_back(*text);
            } else if (std::holds_alternative<std::monostate>(value)) {
                gpuArguments.emplace_back(std::monostate{});
            } else {
                throw EngineError("GPU functions do not accept lists, arrays, or dictionaries");
            }
        }
        try {
            const gpu::Argument result = gpu::call(function, gpuArguments);
            if (std::holds_alternative<std::monostate>(result)) {
                stack_.emplace_back(std::monostate{});
            } else if (const auto* boolean = std::get_if<bool>(&result)) {
                stack_.emplace_back(*boolean);
            } else if (const auto* integer = std::get_if<std::int64_t>(&result)) {
                stack_.emplace_back(*integer);
            } else if (const auto* number = std::get_if<double>(&result)) {
                stack_.emplace_back(*number);
            } else {
                stack_.emplace_back(std::get<std::string>(result));
            }
        } catch (const std::exception& error) {
            throw EngineError(error.what());
        }
    }

    void executeComparison(const std::string& op) {
        const Value right = pop();
        const Value left = pop();
        bool result = false;
        if (isNumber(left) && isNumber(right)) {
            const long double a = asNumber(left);
            const long double b = asNumber(right);
            if (op == "COMPARE_LT") result = a < b;
            else if (op == "COMPARE_LE") result = a <= b;
            else if (op == "COMPARE_GT") result = a > b;
            else result = a >= b;
        } else if (const auto* a = std::get_if<std::string>(&left)) {
            const auto* b = std::get_if<std::string>(&right);
            if (b == nullptr) throw EngineError("cannot compare a string with a non-string");
            if (op == "COMPARE_LT") result = *a < *b;
            else if (op == "COMPARE_LE") result = *a <= *b;
            else if (op == "COMPARE_GT") result = *a > *b;
            else result = *a >= *b;
        } else {
            throw EngineError("ordered comparison expects two numbers or two strings");
        }
        stack_.emplace_back(result);
    }

    Program program_;
    std::istream& input_;
    std::ostream& output_;
    std::vector<Value> constants_;
    std::vector<Value> stack_;
    std::map<std::string, Variable> variables_;
    std::map<std::string, FunctionInfo> functions_;
    std::vector<CallFrame> frames_;
    std::vector<IteratorFrame> iterators_;
    std::vector<ExceptionHandler> handlers_;
    std::size_t instructionPointer_ = 0;
    bool halted_ = false;
    bool numbeerLoaded_ = false;
    bool internetLoaded_ = false;
    bool gpuLoaded_ = false;
    bool timeLoaded_ = false;
    bool loaderLoaded_ = false;
};

static std::vector<Value> parseConstants(const std::vector<Constant>& constants) {
    std::vector<Value> values;
    values.reserve(constants.size());
    for (std::size_t i = 0; i < constants.size(); ++i) {
        const Constant& constant = constants[i];
        const std::string context = "constant " + std::to_string(i);
        if (constant.type == "integer") {
            std::int64_t value = 0;
            const char* begin = constant.text.data();
            const char* end = begin + constant.text.size();
            const auto result = std::from_chars(begin, end, value);
            if (result.ec != std::errc{} || result.ptr != end) {
                throw EngineError(context + ": invalid integer '" + constant.text + "'");
            }
            values.emplace_back(value);
        } else if (constant.type == "float") {
            std::size_t parsed = 0;
            double value = 0.0;
            try {
                value = std::stod(constant.text, &parsed);
            } catch (const std::exception&) {
                throw EngineError(context + ": invalid float '" + constant.text + "'");
            }
            if (parsed != constant.text.size() || !std::isfinite(value)) {
                throw EngineError(context + ": invalid float '" + constant.text + "'");
            }
            values.emplace_back(value);
        } else if (constant.type == "string") {
            values.emplace_back(constant.text);
        } else if (constant.type == "bool") {
            if (constant.text == "true") values.emplace_back(true);
            else if (constant.text == "false") values.emplace_back(false);
            else throw EngineError(context + ": invalid boolean '" + constant.text + "'");
        } else if (constant.type == "null") {
            if (constant.text != "null") {
                throw EngineError(context + ": invalid null literal");
            }
            values.emplace_back(std::monostate{});
        } else {
            throw EngineError(context + ": unknown type '" + constant.type + "'");
        }
    }
    return values;
}

static void runProgram(Program program, std::istream& input, std::ostream& output) {
    VirtualMachine machine(std::move(program), input, output);
    machine.run();
}

} // namespace vilang

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: vilang-engine <bytecode.vbc>\n";
        return 2;
    }

    std::ifstream input(argv[1], std::ios::binary);
    if (!input) {
        std::cerr << "Cannot open bytecode file: " << argv[1] << '\n';
        return 2;
    }

    try {
        vilang::Program program = vilang::loadProgram(input);
        vilang::runProgram(std::move(program), std::cin, std::cout);
    } catch (const vilang::EngineError& error) {
        std::cerr << "ViLang engine error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}