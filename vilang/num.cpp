// Numbeer functions are included by the bytecode engine.
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>
#include <vector>

namespace vilang::numbeer {

static void requireArity(const std::string& name, const std::vector<double>& arguments,
                         std::size_t expected) {
    if (arguments.size() != expected) {
        throw std::runtime_error(name + " expects " + std::to_string(expected) +
                                 (expected == 1 ? " argument" : " arguments"));
    }
}

static double call(const std::string& name, const std::vector<double>& arguments) {
    double result = 0.0;
    if (name == "abs") {
        requireArity(name, arguments, 1);
        result = std::fabs(arguments[0]);
    } else if (name == "sqrt") {
        requireArity(name, arguments, 1);
        if (arguments[0] < 0.0) throw std::runtime_error("sqrt expects a non-negative number");
        result = std::sqrt(arguments[0]);
    } else if (name == "sin") {
        requireArity(name, arguments, 1);
        result = std::sin(arguments[0]);
    } else if (name == "cos") {
        requireArity(name, arguments, 1);
        result = std::cos(arguments[0]);
    } else if (name == "tan") {
        requireArity(name, arguments, 1);
        result = std::tan(arguments[0]);
    } else if (name == "asin") {
        requireArity(name, arguments, 1);
        if (arguments[0] < -1.0 || arguments[0] > 1.0) {
            throw std::runtime_error("asin expects a number between -1 and 1");
        }
        result = std::asin(arguments[0]);
    } else if (name == "acos") {
        requireArity(name, arguments, 1);
        if (arguments[0] < -1.0 || arguments[0] > 1.0) {
            throw std::runtime_error("acos expects a number between -1 and 1");
        }
        result = std::acos(arguments[0]);
    } else if (name == "atan") {
        requireArity(name, arguments, 1);
        result = std::atan(arguments[0]);
    } else if (name == "atan2") {
        requireArity(name, arguments, 2);
        result = std::atan2(arguments[0], arguments[1]);
    } else if (name == "log" || name == "ln") {
        requireArity(name, arguments, 1);
        if (arguments[0] <= 0.0) throw std::runtime_error("log expects a positive number");
        result = std::log(arguments[0]);
    } else if (name == "log10") {
        requireArity(name, arguments, 1);
        if (arguments[0] <= 0.0) {
            throw std::runtime_error("log10 expects a positive number");
        }
        result = std::log10(arguments[0]);
    } else if (name == "exp") {
        requireArity(name, arguments, 1);
        result = std::exp(arguments[0]);
    } else if (name == "floor") {
        requireArity(name, arguments, 1);
        result = std::floor(arguments[0]);
    } else if (name == "ceil") {
        requireArity(name, arguments, 1);
        result = std::ceil(arguments[0]);
    } else if (name == "round") {
        requireArity(name, arguments, 1);
        result = std::round(arguments[0]);
    } else if (name == "trunc") {
        requireArity(name, arguments, 1);
        result = std::trunc(arguments[0]);
    } else if (name == "pow") {
        requireArity(name, arguments, 2);
        result = std::pow(arguments[0], arguments[1]);
    } else if (name == "hypot") {
        requireArity(name, arguments, 2);
        result = std::hypot(arguments[0], arguments[1]);
    } else if (name == "min" || name == "max") {
        if (arguments.size() < 2) {
            throw std::runtime_error(name + " expects at least 2 arguments");
        }
        result = arguments[0];
        for (std::size_t i = 1; i < arguments.size(); ++i) {
            result = name == "min" ? std::fmin(result, arguments[i])
                                   : std::fmax(result, arguments[i]);
        }
    } else if (name == "clamp") {
        requireArity(name, arguments, 3);
        if (arguments[1] > arguments[2]) {
            throw std::runtime_error("clamp minimum cannot exceed its maximum");
        }
        result = std::clamp(arguments[0], arguments[1], arguments[2]);
    } else if (name == "radians") {
        requireArity(name, arguments, 1);
        result = arguments[0] * (std::acos(-1.0) / 180.0);
    } else if (name == "degrees") {
        requireArity(name, arguments, 1);
        result = arguments[0] * (180.0 / std::acos(-1.0));
    } else {
        throw std::runtime_error("unknown Numbeer function '" + name + "'");
    }

    if (!std::isfinite(result)) {
        throw std::runtime_error(name + " result is not finite");
    }
    return result;
}

} // namespace vilang::numbeer