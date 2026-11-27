#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <istream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#if !defined(VILANG_COMPILER) && defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <shellapi.h>
#endif

namespace vilang::loader {

[[maybe_unused]] static std::filesystem::path resolveSourcePath(
    const std::string& requested, const std::string& currentFile) {
    std::filesystem::path path = std::filesystem::u8path(requested);
    if (path.is_relative() && !currentFile.empty()) {
        path = std::filesystem::u8path(currentFile).parent_path() / path;
    }
    std::error_code error;
    const std::filesystem::path absolute = std::filesystem::absolute(path, error);
    if (error) {
        throw std::runtime_error("cannot resolve file path '" + requested +
                                 "': " + error.message());
    }
    return absolute.lexically_normal();
}

static std::filesystem::path canonicalSourcePath(const std::filesystem::path& path) {
    std::error_code error;
    std::filesystem::path canonical = std::filesystem::weakly_canonical(path, error);
    if (error) {
        throw std::runtime_error("cannot normalize file path '" + path.u8string() +
                                 "': " + error.message());
    }
    return canonical;
}

[[maybe_unused]] static std::string readSourceFile(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) {
        throw std::runtime_error("cannot open source file '" + path.u8string() + "'");
    }
    const std::streampos end = input.tellg();
    constexpr std::streamoff maximumSourceBytes = 16 * 1024 * 1024;
    if (end < 0 || end > maximumSourceBytes) {
        throw std::runtime_error("source file exceeds the 16 MiB limit");
    }
    std::string source(static_cast<std::size_t>(end), '\0');
    input.seekg(0, std::ios::beg);
    if (!source.empty()) {
        input.read(source.data(), static_cast<std::streamsize>(source.size()));
    }
    if (!input && !input.eof()) {
        throw std::runtime_error("failed to read source file '" + path.u8string() + "'");
    }
    return source;
}

} // namespace vilang::loader

#ifndef VILANG_COMPILER
namespace vilang::loader {

static std::string lowercase(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char character) {
                       return static_cast<char>(std::tolower(character));
                   });
    return value;
}

static std::string trim(std::string value) {
    const std::size_t first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    const std::size_t last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

static bool confirmBluetooth(const std::string& action, std::istream& input,
                             std::ostream& output) {
    output << "Open the Windows Bluetooth File Transfer wizard to " << action
           << " a file? (yes/no): " << std::flush;
    if (!output) throw std::runtime_error("failed to write Bluetooth permission prompt");

    std::string answer;
    if (!std::getline(input, answer)) {
        throw std::runtime_error("failed to read Bluetooth permission response");
    }
    answer = lowercase(trim(std::move(answer)));
    if (answer == "yes" || answer == "y" || answer == "да") return true;
    if (answer == "no" || answer == "n" || answer == "нет") return false;
    throw std::runtime_error("Bluetooth permission response must be yes or no");
}

#ifdef _WIN32
static std::wstring toWide(const std::string& text) {
    if (text.empty() ||
        text.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        throw std::runtime_error("invalid file path length");
    }
    const int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
                                           text.data(), static_cast<int>(text.size()),
                                           nullptr, 0);
    if (length == 0) throw std::runtime_error("file path is not valid UTF-8");
    std::wstring result(static_cast<std::size_t>(length), L'\0');
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                            static_cast<int>(text.size()), result.data(), length) == 0) {
        throw std::runtime_error("failed to convert file path");
    }
    return result;
}

static std::wstring quoteArgument(const std::wstring& argument) {
    std::wstring result = L"\"";
    std::size_t backslashes = 0;
    for (wchar_t character : argument) {
        if (character == L'\\') {
            ++backslashes;
        } else if (character == L'"') {
            result.append(backslashes * 2 + 1, L'\\');
            result += character;
            backslashes = 0;
        } else {
            result.append(backslashes, L'\\');
            result += character;
            backslashes = 0;
        }
    }
    result.append(backslashes * 2, L'\\');
    result += L'"';
    return result;
}

static std::string runForeignFile(const std::wstring& interpreter,
                                  const std::wstring& sourcePath) {
    wchar_t executable[MAX_PATH]{};
    const DWORD executableLength =
        SearchPathW(nullptr, interpreter.c_str(), nullptr, MAX_PATH, executable, nullptr);
    if (executableLength == 0 || executableLength >= MAX_PATH) {
        throw std::runtime_error("required interpreter '" +
                                 std::string(interpreter.begin(), interpreter.end()) +
                                 "' was not found on PATH");
    }

    SECURITY_ATTRIBUTES security{};
    security.nLength = sizeof(security);
    security.bInheritHandle = TRUE;
    HANDLE readPipe = nullptr;
    HANDLE writePipe = nullptr;
    if (!CreatePipe(&readPipe, &writePipe, &security, 0)) {
        throw std::runtime_error("failed to create script output pipe");
    }
    if (!SetHandleInformation(readPipe, HANDLE_FLAG_INHERIT, 0)) {
        CloseHandle(readPipe);
        CloseHandle(writePipe);
        throw std::runtime_error("failed to configure script output pipe");
    }

    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdOutput = writePipe;
    startup.hStdError = writePipe;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    PROCESS_INFORMATION process{};
    std::wstring command = quoteArgument(executable) + L" " +
                           quoteArgument(sourcePath);
    if (!CreateProcessW(executable, command.data(), nullptr, nullptr, TRUE,
                        CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process)) {
        CloseHandle(readPipe);
        CloseHandle(writePipe);
        throw std::runtime_error("failed to start the foreign-language interpreter");
    }
    CloseHandle(writePipe);

    std::string result;
    constexpr std::size_t maximumOutputBytes = 16 * 1024 * 1024;
    const ULONGLONG deadline = GetTickCount64() + 60000;
    bool finished = false;
    while (!finished) {
        DWORD available = 0;
        if (!PeekNamedPipe(readPipe, nullptr, 0, nullptr, &available, nullptr)) {
            const DWORD error = GetLastError();
            if (error != ERROR_BROKEN_PIPE) {
                TerminateProcess(process.hProcess, 1);
                WaitForSingleObject(process.hProcess, INFINITE);
                CloseHandle(readPipe);
                CloseHandle(process.hThread);
                CloseHandle(process.hProcess);
                throw std::runtime_error("failed to read foreign-language output");
            }
            finished = true;
            continue;
        }
        if (available != 0) {
            char buffer[4096];
            const DWORD requested =
                std::min<DWORD>(available, static_cast<DWORD>(sizeof(buffer)));
            DWORD bytesRead = 0;
            if (!ReadFile(readPipe, buffer, requested, &bytesRead, nullptr)) {
                const DWORD error = GetLastError();
                if (error == ERROR_BROKEN_PIPE) {
                    finished = true;
                    continue;
                }
                TerminateProcess(process.hProcess, 1);
                WaitForSingleObject(process.hProcess, INFINITE);
                CloseHandle(readPipe);
                CloseHandle(process.hThread);
                CloseHandle(process.hProcess);
                throw std::runtime_error("failed to read foreign-language output");
            }
            if (bytesRead > maximumOutputBytes - result.size()) {
                TerminateProcess(process.hProcess, 1);
                WaitForSingleObject(process.hProcess, INFINITE);
                CloseHandle(readPipe);
                CloseHandle(process.hThread);
                CloseHandle(process.hProcess);
                throw std::runtime_error("foreign-language output exceeds the 16 MiB limit");
            }
            result.append(buffer, bytesRead);
            continue;
        }

        const DWORD processStatus = WaitForSingleObject(process.hProcess, 50);
        if (processStatus == WAIT_OBJECT_0) {
            finished = true;
        } else if (processStatus == WAIT_FAILED) {
            TerminateProcess(process.hProcess, 1);
            WaitForSingleObject(process.hProcess, INFINITE);
            CloseHandle(readPipe);
            CloseHandle(process.hThread);
            CloseHandle(process.hProcess);
            throw std::runtime_error("failed while waiting for foreign-language script");
        } else if (GetTickCount64() >= deadline) {
            TerminateProcess(process.hProcess, 1);
            WaitForSingleObject(process.hProcess, INFINITE);
            CloseHandle(readPipe);
            CloseHandle(process.hThread);
            CloseHandle(process.hProcess);
            throw std::runtime_error("foreign-language script exceeded the 60 second limit");
        }
    }

    DWORD exitCode = 0;
    if (!GetExitCodeProcess(process.hProcess, &exitCode)) {
        CloseHandle(readPipe);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        throw std::runtime_error("failed to read foreign-language exit code");
    }
    CloseHandle(readPipe);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    if (exitCode != 0) {
        throw std::runtime_error("foreign-language script exited with code " +
                                 std::to_string(exitCode) + ": " + result);
    }
    return result;
}
#endif

static Value call(const std::string& name, const std::vector<Value>& arguments,
                  std::istream& input, std::ostream& output) {
    if (name == "load_file") {
        if (arguments.size() != 1 ||
            std::get_if<std::string>(&arguments[0]) == nullptr) {
            throw std::runtime_error("load file expects one source path");
        }
        const std::filesystem::path path =
            canonicalSourcePath(std::filesystem::u8path(
                std::get<std::string>(arguments[0])));
        const std::string extension = lowercase(path.extension().string());
#ifdef _WIN32
        const std::wstring interpreter =
            extension == ".py" ? L"python.exe"
                               : extension == ".js" ? L"node.exe" : L"";
        if (interpreter.empty()) {
            throw std::runtime_error("load file supports .vi, .py, and .js files");
        }
        output << runForeignFile(interpreter, toWide(path.u8string()));
        if (!output) throw std::runtime_error("failed to write foreign-language output");
        return true;
#else
        throw std::runtime_error("Python and JavaScript file loading is supported on Windows only");
#endif
    }
    if (name == "download" || name == "download_file") {
        if (arguments.size() != 2 ||
            std::get_if<std::string>(&arguments[0]) == nullptr ||
            std::get_if<std::string>(&arguments[1]) == nullptr) {
            throw std::runtime_error(name +
                                     " expects an HTTP(S) URL and destination path");
        }
        internet::download(std::get<std::string>(arguments[0]),
                           std::get<std::string>(arguments[1]));
        return true;
    }

    std::wstring mode;
    std::string action;
    if (name == "bluetooth_send") {
        mode = L"-send";
        action = "send";
    } else if (name == "bluetooth_receive") {
        mode = L"-receive";
        action = "receive";
    } else {
        throw std::runtime_error("unknown loader function '" + name + "'");
    }
    if (!arguments.empty()) {
        throw std::runtime_error(name + " expects no arguments");
    }
    if (!confirmBluetooth(action, input, output)) {
        output << "Bluetooth operation cancelled.\n";
        if (!output) throw std::runtime_error("failed to report Bluetooth cancellation");
        return false;
    }

#ifdef _WIN32
    wchar_t systemDirectory[MAX_PATH]{};
    const UINT length = GetSystemDirectoryW(systemDirectory, MAX_PATH);
    if (length == 0 || length >= MAX_PATH) {
        throw std::runtime_error("failed to locate the Windows Bluetooth transfer wizard");
    }
    std::wstring executable(systemDirectory, length);
    executable += L"\\fsquirt.exe";
    const HINSTANCE result = ShellExecuteW(nullptr, L"open", executable.c_str(),
                                           mode.c_str(), nullptr, SW_SHOWNORMAL);
    if (reinterpret_cast<std::intptr_t>(result) <= 32) {
        throw std::runtime_error("failed to open the Windows Bluetooth transfer wizard");
    }
    output << "Bluetooth transfer wizard opened; complete or cancel the transfer there.\n";
    if (!output) throw std::runtime_error("failed to report Bluetooth wizard status");
    return true;
#else
    (void)mode;
    throw std::runtime_error("Bluetooth file transfer is currently supported on Windows only");
#endif
}

} // namespace vilang::loader
#endif