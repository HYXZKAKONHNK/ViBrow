#include <cctype>
#include <cstddef>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <winhttp.h>
#endif

namespace vilang::internet {

#ifdef _WIN32

struct Response {
    std::string body;
    std::string headers;
    std::string finalUrl;
    std::size_t status = 0;
};

class InternetHandle {
public:
    explicit InternetHandle(HINTERNET handle) : handle_(handle) {}
    ~InternetHandle() {
        if (handle_ != nullptr) {
            WinHttpCloseHandle(handle_);
        }
    }
    InternetHandle(const InternetHandle&) = delete;
    InternetHandle& operator=(const InternetHandle&) = delete;
    HINTERNET get() const { return handle_; }

private:
    HINTERNET handle_;
};

static HINTERNET sessionHandle = nullptr;
static std::string userAgent = "ViLang-Internet/2.0";
static DWORD connectTimeout = 10000;
static DWORD receiveTimeout = 30000;
static std::size_t maxResponseBytes = 16 * 1024 * 1024;
static Response lastResponse{};

static void closeSession() {
    if (sessionHandle != nullptr) {
        WinHttpCloseHandle(sessionHandle);
        sessionHandle = nullptr;
    }
}

static std::wstring toWide(const std::string& value) {
    if (value.empty() ||
        value.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        throw std::runtime_error("invalid string length");
    }
    const int inputLength = static_cast<int>(value.size());
    const int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
                                           value.data(), inputLength, nullptr, 0);
    if (length == 0) {
        throw std::runtime_error("text is not valid UTF-8");
    }
    std::wstring result(static_cast<std::size_t>(length), L'\0');
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), inputLength,
                            result.data(), length) == 0) {
        throw std::runtime_error("failed to convert UTF-8 text");
    }
    return result;
}

static std::string toUtf8(const std::wstring& value) {
    if (value.empty()) return {};
    const int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS,
                                           value.data(), static_cast<int>(value.size()),
                                           nullptr, 0, nullptr, nullptr);
    if (length == 0) return {};
    std::string result(static_cast<std::size_t>(length), '\0');
    WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
                        static_cast<int>(value.size()), result.data(), length,
                        nullptr, nullptr);
    return result;
}

static std::string lowerAscii(std::string value) {
    for (char& character : value) {
        if (character >= 'A' && character <= 'Z') {
            character = static_cast<char>(character - 'A' + 'a');
        }
    }
    return value;
}

static bool startsWithNoCase(const std::string& value, const std::string& prefix) {
    return value.size() >= prefix.size() &&
           lowerAscii(value.substr(0, prefix.size())) == lowerAscii(prefix);
}

static bool validHost(const std::wstring& host) {
    if (host.empty()) return false;
    for (wchar_t character : host) {
        if ((character >= L'a' && character <= L'z') ||
            (character >= L'A' && character <= L'Z') ||
            (character >= L'0' && character <= L'9') ||
            character == L'.' || character == L'-' ||
            character == L':' || character == L'_') {
            continue;
        }
        return false;
    }
    return true;
}

static std::string hostPart(const std::string& url) {
    const std::size_t scheme = url.find("://");
    if (scheme == std::string::npos) return {};
    const std::size_t authorityStart = scheme + 3;
    const std::size_t authorityEnd = url.find_first_of("/?#", authorityStart);
    std::string authority = url.substr(authorityStart, authorityEnd == std::string::npos
                                                          ? std::string::npos
                                                          : authorityEnd - authorityStart);
    const std::size_t at = authority.rfind('@');
    if (at != std::string::npos) authority.erase(0, at + 1);
    if (!authority.empty() && authority.front() == '[') {
        const std::size_t closing = authority.find(']');
        return closing == std::string::npos ? authority : authority.substr(0, closing + 1);
    }
    const std::size_t colon = authority.find(':');
    return colon == std::string::npos ? authority : authority.substr(0, colon);
}

static std::string resolveUrl(const std::string& baseUrl,
                              const std::string& location) {
    if (startsWithNoCase(location, "https://") ||
        startsWithNoCase(location, "http://")) {
        return location;
    }
    const std::size_t scheme = baseUrl.find("://");
    if (scheme == std::string::npos) {
        throw std::runtime_error("invalid base URL");
    }
    const std::size_t authorityStart = scheme + 3;
    const std::size_t authorityEnd = baseUrl.find_first_of("/?#", authorityStart);
    const std::string origin = baseUrl.substr(
        0, authorityEnd == std::string::npos ? baseUrl.size() : authorityEnd);
    if (startsWithNoCase(location, "//")) {
        return baseUrl.substr(0, scheme + 1) + location;
    }
    if (!location.empty() && location.front() == '/') {
        return origin + location;
    }
    const std::size_t slash = baseUrl.find_last_of('/');
    if (slash == std::string::npos || slash < authorityStart) {
        return origin + "/" + location;
    }
    return baseUrl.substr(0, slash + 1) + location;
}

static void validateUrl(const std::string& url) {
    constexpr std::size_t maxUrlBytes = 8192;
    if (url.size() > maxUrlBytes) {
        throw std::runtime_error("URL exceeds the 8 KiB limit");
    }
    if (!startsWithNoCase(url, "http://") &&
        !startsWithNoCase(url, "https://")) {
        throw std::runtime_error("only HTTP and HTTPS URLs are supported");
    }
    for (unsigned char character : url) {
        if (character <= 0x20 || character == 0x7f) {
            throw std::runtime_error("URL must not contain spaces or control characters");
        }
    }
    const std::size_t authorityStart = url.find("://");
    if (authorityStart == std::string::npos) {
        throw std::runtime_error("invalid URL");
    }
    const std::size_t hostStart = authorityStart + 3;
    const std::size_t hostEnd = url.find_first_of("/?#", hostStart);
    const std::string authority = url.substr(hostStart, hostEnd == std::string::npos
                                                          ? std::string::npos
                                                          : hostEnd - hostStart);
    if (authority.empty() || authority.find('@') != std::string::npos) {
        throw std::runtime_error("URL must contain a host and must not contain credentials");
    }
    if (hostPart(url).empty()) {
        throw std::runtime_error("URL host cannot be empty");
    }
}

static HINTERNET getSession() {
    if (sessionHandle != nullptr) return sessionHandle;
    const std::wstring agent = toWide(userAgent);
    sessionHandle = WinHttpOpen(agent.c_str(),
                                WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                                WINHTTP_NO_PROXY_NAME,
                                WINHTTP_NO_PROXY_BYPASS,
                                0);
    if (sessionHandle == nullptr) {
        throw std::runtime_error("failed to initialize internet session");
    }
    if (!WinHttpSetTimeouts(sessionHandle, 5000, connectTimeout,
                            receiveTimeout, receiveTimeout)) {
        throw std::runtime_error("failed to configure internet timeouts");
    }
    return sessionHandle;
}

static std::string findLocation(const std::wstring& rawHeaders) {
    const std::string headers = toUtf8(rawHeaders);
    const std::size_t count = headers.size();
    std::size_t position = 0;
    while (position < count) {
        const std::size_t end = headers.find("\r\n", position);
        const std::size_t lineEnd = end == std::string::npos ? count : end;
        const std::string line = headers.substr(position, lineEnd - position);
        const std::size_t colon = line.find(':');
        if (colon != std::string::npos) {
            std::string name = lowerAscii(line.substr(0, colon));
            while (!name.empty() && (name.back() == ' ' || name.back() == '\t')) {
                name.pop_back();
            }
            if (name == "location") {
                std::string value = line.substr(colon + 1);
                const std::size_t first = value.find_first_not_of(" \t");
                if (first != std::string::npos) {
                    value = value.substr(first);
                }
                const std::size_t last = value.find_last_not_of(" \t");
                if (last != std::string::npos) value.resize(last + 1);
                return value;
            }
        }
        if (end == std::string::npos) break;
        position = end + 2;
    }
    return {};
}

static std::string stripSensitiveHeaders(const std::string& headers,
                                         const std::string& oldUrl,
                                         const std::string& newUrl) {
    if (hostPart(oldUrl) == hostPart(newUrl)) return headers;

    std::istringstream input(headers);
    std::ostringstream output;
    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        const std::size_t colon = line.find(':');
        if (colon != std::string::npos) {
            std::string name = lowerAscii(line.substr(0, colon));
            while (!name.empty() && (name.back() == ' ' || name.back() == '\t')) {
                name.pop_back();
            }
            if (name == "authorization" || name == "cookie" ||
                name == "proxy-authorization") {
                continue;
            }
        }
        output << line << "\r\n";
    }
    return output.str();
}

static Response request(const std::string& method,
                        const std::string& url,
                        const std::string& body,
                        const std::string& headers) {
    validateUrl(url);

    std::string currentUrl = url;
    std::string requestHeaders = headers;
    std::wstring requestMethod = toWide(method);

    for (std::size_t redirectCount = 0; redirectCount <= 10; ++redirectCount) {
        validateUrl(currentUrl);
        const std::wstring wideUrl = toWide(currentUrl);
        URL_COMPONENTS components{};
        components.dwStructSize = sizeof(components);
        std::wstring scheme(16, L'\0');
        std::wstring host(1024, L'\0');
        std::wstring path(8192, L'\0');
        std::wstring extra(8192, L'\0');
        components.lpszScheme = scheme.data();
        components.dwSchemeLength = static_cast<DWORD>(scheme.size());
        components.lpszHostName = host.data();
        components.dwHostNameLength = static_cast<DWORD>(host.size());
        components.lpszUrlPath = path.data();
        components.dwUrlPathLength = static_cast<DWORD>(path.size());
        components.lpszExtraInfo = extra.data();
        components.dwExtraInfoLength = static_cast<DWORD>(extra.size());
        if (!WinHttpCrackUrl(wideUrl.c_str(), 0, 0, &components)) {
            throw std::runtime_error("invalid URL");
        }
        if (components.nScheme != INTERNET_SCHEME_HTTP &&
            components.nScheme != INTERNET_SCHEME_HTTPS) {
            throw std::runtime_error("only HTTP and HTTPS URLs are supported");
        }
        if (components.dwUserNameLength != 0 || components.dwPasswordLength != 0) {
            throw std::runtime_error("URL must not contain credentials");
        }

        const std::wstring hostName(components.lpszHostName,
                                    components.dwHostNameLength);
        if (!validHost(hostName)) {
            throw std::runtime_error("URL host contains an invalid character");
        }
        const std::wstring urlPath = components.dwUrlPathLength == 0
                                         ? std::wstring(L"/")
                                         : std::wstring(components.lpszUrlPath,
                                                        components.dwUrlPathLength);
        std::wstring extraInfo;
        if (components.dwExtraInfoLength != 0) {
            extraInfo.assign(components.lpszExtraInfo, components.dwExtraInfoLength);
        }
        std::wstring fullPath = urlPath + extraInfo;
        if (fullPath.empty()) fullPath = L"/";

        InternetHandle connection(WinHttpConnect(getSession(), hostName.c_str(),
                                                 components.nPort, 0));
        if (connection.get() == nullptr) {
            throw std::runtime_error("failed to connect to server");
        }

        const DWORD requestFlags =
            components.nScheme == INTERNET_SCHEME_HTTPS ? WINHTTP_FLAG_SECURE : 0;
        InternetHandle httpRequest(
            WinHttpOpenRequest(connection.get(), requestMethod.c_str(),
                               fullPath.c_str(), nullptr, WINHTTP_NO_REFERER,
                               WINHTTP_DEFAULT_ACCEPT_TYPES, requestFlags));
        if (httpRequest.get() == nullptr) {
            throw std::runtime_error("failed to create HTTP request");
        }

        DWORD redirectPolicy = WINHTTP_OPTION_REDIRECT_POLICY_NEVER;
        if (!WinHttpSetOption(httpRequest.get(), WINHTTP_OPTION_REDIRECT_POLICY,
                              &redirectPolicy, sizeof(redirectPolicy))) {
            throw std::runtime_error("failed to configure redirect handling");
        }

        if (!headers.empty()) {
            std::wstring wideHeaders = toWide(headers);
            if (headers.find('\n') == std::string::npos) {
                wideHeaders += L"\r\n";
            }
            if (!WinHttpAddRequestHeaders(httpRequest.get(), wideHeaders.c_str(),
                                          static_cast<DWORD>(-1L),
                                          WINHTTP_ADDREQ_FLAG_ADD |
                                          WINHTTP_ADDREQ_FLAG_REPLACE)) {
                throw std::runtime_error("failed to add request headers");
            }
        }

        const bool hasBody = !body.empty();
        const void* bodyPointer = hasBody
                                      ? static_cast<const void*>(body.data())
                                      : WINHTTP_NO_REQUEST_DATA;
        const DWORD bodySize = hasBody
                                   ? static_cast<DWORD>(body.size())
                                   : 0;
        if (bodySize != body.size()) {
            throw std::runtime_error("request body is too large");
        }
        if (!WinHttpSendRequest(httpRequest.get(), WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                                const_cast<void*>(bodyPointer), bodySize, bodySize, 0) ||
            !WinHttpReceiveResponse(httpRequest.get(), nullptr)) {
            throw std::runtime_error("HTTP request failed");
        }

        DWORD statusCode = 0;
        DWORD statusSize = sizeof(statusCode);
        if (!WinHttpQueryHeaders(httpRequest.get(),
                                 WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                                 WINHTTP_HEADER_NAME_BY_INDEX, &statusCode, &statusSize,
                                 WINHTTP_NO_HEADER_INDEX)) {
            throw std::runtime_error("failed to read response status");
        }

        DWORD headerSize = 0;
        WinHttpQueryHeaders(httpRequest.get(), WINHTTP_QUERY_RAW_HEADERS_CRLF,
                            WINHTTP_HEADER_NAME_BY_INDEX, nullptr, &headerSize,
                            WINHTTP_NO_HEADER_INDEX);
        std::wstring rawHeaders;
        if (GetLastError() == ERROR_INSUFFICIENT_BUFFER && headerSize != 0) {
            rawHeaders.resize(headerSize / sizeof(wchar_t));
            if (!WinHttpQueryHeaders(httpRequest.get(), WINHTTP_QUERY_RAW_HEADERS_CRLF,
                                     WINHTTP_HEADER_NAME_BY_INDEX, rawHeaders.data(),
                                     &headerSize, WINHTTP_NO_HEADER_INDEX)) {
                rawHeaders.clear();
            } else {
                rawHeaders.resize(headerSize / sizeof(wchar_t));
                while (!rawHeaders.empty() && rawHeaders.back() == L'\0') {
                    rawHeaders.pop_back();
                }
            }
        }
        const std::string responseHeaders = toUtf8(rawHeaders);

        if (statusCode >= 300 && statusCode < 400) {
            const std::string location = findLocation(rawHeaders);
            if (location.empty()) {
                throw std::runtime_error("HTTP redirect returned without Location");
            }
            if (redirectCount == 10) {
                throw std::runtime_error("too many HTTP redirects");
            }
            const std::string newUrl = resolveUrl(currentUrl, location);
            validateUrl(newUrl);
            if (startsWithNoCase(currentUrl, "https://") &&
                startsWithNoCase(newUrl, "http://")) {
                throw std::runtime_error("refusing insecure redirect from HTTPS");
            }
            requestHeaders = stripSensitiveHeaders(requestHeaders, currentUrl, newUrl);
            currentUrl = newUrl;
            if (statusCode == 303 ||
                (statusCode == 302 && (method == "POST" || method == "PUT" ||
                                       method == "PATCH"))) {
                requestMethod = L"GET";
            }
            if (statusCode == 301 || statusCode == 302 || statusCode == 303) {
                if (method == "POST" || method == "PUT" || method == "PATCH") {
                    requestMethod = L"GET";
                }
            }
            continue;
        }

        std::string responseBody;
        if (method != "HEAD") {
            for (;;) {
                DWORD available = 0;
                if (!WinHttpQueryDataAvailable(httpRequest.get(), &available)) {
                    throw std::runtime_error("failed to read HTTP response");
                }
                if (available == 0) break;
                if (available > maxResponseBytes - responseBody.size()) {
                    throw std::runtime_error("HTTP response exceeds the 16 MiB limit");
                }
                const std::size_t oldSize = responseBody.size();
                responseBody.resize(oldSize + available);
                DWORD bytesRead = 0;
                if (!WinHttpReadData(httpRequest.get(), responseBody.data() + oldSize,
                                     available, &bytesRead)) {
                    throw std::runtime_error("failed to read HTTP response");
                }
                responseBody.resize(oldSize + bytesRead);
                if (bytesRead == 0) break;
            }
        }

        lastResponse = {responseBody, responseHeaders, currentUrl,
                        static_cast<std::size_t>(statusCode)};
        if (statusCode < 200 || statusCode >= 300) {
            throw std::runtime_error("HTTP request returned status " +
                                     std::to_string(statusCode));
        }
        return lastResponse;
    }
    throw std::runtime_error("too many HTTP redirects");
}

static Response get(const std::string& url) {
    return request("GET", url, "", "");
}

static Response post(const std::string& url, const std::string& body,
                     const std::string& headers) {
    return request("POST", url, body, headers);
}

static Response put(const std::string& url, const std::string& body,
                    const std::string& headers) {
    return request("PUT", url, body, headers);
}

static Response patch(const std::string& url, const std::string& body,
                      const std::string& headers) {
    return request("PATCH", url, body, headers);
}

static Response remove(const std::string& url, const std::string& body,
                       const std::string& headers) {
    return request("DELETE", url, body, headers);
}

static Response head(const std::string& url) {
    return request("HEAD", url, "", "");
}

static std::string headers(const std::string& url) {
    return head(url).headers;
}

static void download(const std::string& url, const std::string& path) {
    if (path.empty()) throw std::runtime_error("download path cannot be empty");
    const Response response = get(url);
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("cannot open download destination");
    output.write(response.body.data(), static_cast<std::streamsize>(response.body.size()));
    if (!output) throw std::runtime_error("failed to write download destination");
}

static void setTimeout(DWORD milliseconds) {
    if (milliseconds < 1000 || milliseconds > 300000) {
        throw std::runtime_error("timeout must be between 1000 and 300000 ms");
    }
    connectTimeout = milliseconds;
    receiveTimeout = milliseconds;
    closeSession();
}

static void setUserAgent(const std::string& agent) {
    if (agent.empty() || agent.size() > 1024 ||
        agent.find('\r') != std::string::npos ||
        agent.find('\n') != std::string::npos) {
        throw std::runtime_error("invalid user agent");
    }
    userAgent = agent;
    closeSession();
}

static void clearCookies() {
    closeSession();
}

static std::size_t status(const std::string& url) {
    return head(url).status;
}

static std::string responseHeaders() {
    return lastResponse.headers;
}

static std::size_t responseStatus() {
    return lastResponse.status;
}

static std::string finalUrl() {
    return lastResponse.finalUrl;
}

#else

struct Response {
    std::string body;
    std::string headers;
    std::string finalUrl;
    std::size_t status = 0;
};

static Response request(const std::string&, const std::string&,
                        const std::string&, const std::string&) {
    throw std::runtime_error("internet library is currently supported on Windows only");
}
static Response get(const std::string& url) { return request("GET", url, "", ""); }
static Response post(const std::string& url, const std::string& body,
                     const std::string& headers) {
    return request("POST", url, body, headers);
}
static Response put(const std::string& url, const std::string& body,
                    const std::string& headers) {
    return request("PUT", url, body, headers);
}
static Response patch(const std::string& url, const std::string& body,
                      const std::string& headers) {
    return request("PATCH", url, body, headers);
}
static Response remove(const std::string& url, const std::string& body,
                       const std::string& headers) {
    return request("DELETE", url, body, headers);
}
static Response head(const std::string& url) { return request("HEAD", url, "", ""); }
static std::string headers(const std::string& url) {
    return head(url).headers;
}
static void download(const std::string&, const std::string&) {
    throw std::runtime_error("internet library is currently supported on Windows only");
}
static void setTimeout(DWORD) {
    throw std::runtime_error("internet library is currently supported on Windows only");
}
static void setUserAgent(const std::string&) {
    throw std::runtime_error("internet library is currently supported on Windows only");
}
static void clearCookies() {}
static std::size_t status(const std::string& url) { return head(url).status; }
static std::string responseHeaders() { return {}; }
static std::size_t responseStatus() { return 0; }
static std::string finalUrl() { return {}; }

#endif

} // namespace vilang::internet
