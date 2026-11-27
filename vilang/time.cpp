#include <chrono>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <variant>
#include <vector>

namespace vilang::time {

using TimerClock = std::chrono::steady_clock;

static std::map<std::int64_t, TimerClock::time_point>& timers() {
    static std::map<std::int64_t, TimerClock::time_point> activeTimers;
    return activeTimers;
}

static std::int64_t& nextTimerId() {
    static std::int64_t nextId = 1;
    return nextId;
}

static void requireArity(const std::string& name, const std::vector<Value>& arguments,
                         std::size_t expected) {
    if (arguments.size() != expected) {
        throw std::runtime_error(name + " expects " + std::to_string(expected) +
                                 (expected == 1 ? " argument" : " arguments"));
    }
}

static double asMilliseconds(const Value& value, const std::string& name) {
    double milliseconds = 0.0;
    if (const auto* integer = std::get_if<std::int64_t>(&value)) {
        milliseconds = static_cast<double>(*integer);
    } else if (const auto* number = std::get_if<double>(&value)) {
        milliseconds = *number;
    } else {
        throw std::runtime_error(name + " expects a number of milliseconds");
    }
    if (!std::isfinite(milliseconds)) {
        throw std::runtime_error(name + " expects a finite number");
    }
    return milliseconds;
}

static std::int64_t timerId(const std::string& name, const std::vector<Value>& arguments) {
    requireArity(name, arguments, 1);
    const auto* id = std::get_if<std::int64_t>(&arguments[0]);
    if (id == nullptr || *id <= 0) {
        throw std::runtime_error(name + " expects a timer ID returned by timer_start()");
    }
    if (timers().find(*id) == timers().end()) {
        throw std::runtime_error(name + " received an unknown or stopped timer ID");
    }
    return *id;
}

static double elapsedMilliseconds(std::int64_t id) {
    return std::chrono::duration<double, std::milli>(
               TimerClock::now() - timers().at(id)).count();
}

static std::string localTime(const char* format) {
    const std::time_t current = std::chrono::system_clock::to_time_t(
        std::chrono::system_clock::now());
    std::tm local{};
#ifdef _WIN32
    if (localtime_s(&local, &current) != 0) {
        throw std::runtime_error("failed to read the local time");
    }
#else
    if (localtime_r(&current, &local) == nullptr) {
        throw std::runtime_error("failed to read the local time");
    }
#endif
    std::ostringstream result;
    result << std::put_time(&local, format);
    if (!result) {
        throw std::runtime_error("failed to format the local time");
    }
    return result.str();
}

static Value call(const std::string& name, const std::vector<Value>& arguments) {
    if (name == "time" || name == "time_now") {
        requireArity(name, arguments, 0);
        return localTime("%H:%M:%S");
    }
    if (name == "date" || name == "date_now") {
        requireArity(name, arguments, 0);
        return localTime("%Y-%m-%d");
    }
    if (name == "datetime") {
        requireArity(name, arguments, 0);
        return localTime("%Y-%m-%d %H:%M:%S");
    }
    if (name == "timestamp") {
        requireArity(name, arguments, 0);
        return static_cast<std::int64_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());
    }
    if (name == "sleep") {
        requireArity(name, arguments, 1);
        const double milliseconds = asMilliseconds(arguments[0], name);
        constexpr double maximumSleepMilliseconds = 86400000.0;
        if (milliseconds < 0.0 || milliseconds > maximumSleepMilliseconds) {
            throw std::runtime_error("sleep duration must be from 0 to 86400000 milliseconds");
        }
        std::this_thread::sleep_for(
            std::chrono::duration<double, std::milli>(milliseconds));
        return std::monostate{};
    }
    if (name == "timer_start") {
        requireArity(name, arguments, 0);
        std::int64_t& nextId = nextTimerId();
        if (nextId == std::numeric_limits<std::int64_t>::max()) {
            throw std::runtime_error("no more timer IDs are available");
        }
        const std::int64_t id = nextId++;
        timers().emplace(id, TimerClock::now());
        return id;
    }
    if (name == "timer_elapsed") {
        const std::int64_t id = timerId(name, arguments);
        return elapsedMilliseconds(id);
    }
    if (name == "timer_reset") {
        const std::int64_t id = timerId(name, arguments);
        timers().at(id) = TimerClock::now();
        return std::monostate{};
    }
    if (name == "timer_stop") {
        const std::int64_t id = timerId(name, arguments);
        const double elapsed = elapsedMilliseconds(id);
        timers().erase(id);
        return elapsed;
    }
    throw std::runtime_error("unknown time function '" + name + "'");
}

} // namespace vilang::time