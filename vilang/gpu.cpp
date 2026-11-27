#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <windowsx.h>
#include <GL/gl.h>
#endif

namespace vilang::gpu {

using Argument = std::variant<std::monostate, bool, std::int64_t, double, std::string>;

struct Color {
    float red;
    float green;
    float blue;
    float alpha;
};

struct Point {
    float x;
    float y;
};

enum class ShapeType {
    Rectangle,
    RoundedRectangle,
    Circle,
    Ellipse,
    Line,
    Text,
    Button
};

struct Shape {
    ShapeType type;
    float x = 0.0F;
    float y = 0.0F;
    float width = 0.0F;
    float height = 0.0F;
    float radius = 0.0F;
    float strokeWidth = 1.0F;
    Color color{0.0F, 0.0F, 0.0F, 1.0F};
    std::string text;
    unsigned int fontSize = 18;
};

struct State {
    std::string title = "ViLang OpenGL";
    int width = 800;
    int height = 600;
    Color background{0.12F, 0.13F, 0.16F, 1.0F};
    bool normalizedCoordinates = false;
    bool centerCoordinates = false;
    bool configured = false;
    bool shown = false;
    bool buttonClicked = false;
    std::vector<Shape> shapes;
#ifdef _WIN32
    HWND window = nullptr;
    HDC deviceContext = nullptr;
    HGLRC renderContext = nullptr;
    HFONT font = nullptr;
    GLuint fontLists = 0;
    std::size_t hoveredButton = std::numeric_limits<std::size_t>::max();
#endif
};

static State state;

static std::runtime_error error(const std::string& message) {
    return std::runtime_error("gpu: " + message);
}

static void requireArity(const std::string& name, const std::vector<Argument>& arguments,
                         std::size_t count) {
    if (arguments.size() != count) {
        throw error(name + " expects " + std::to_string(count) +
                    (count == 1 ? " argument" : " arguments"));
    }
}

static void requireConfigured() {
    if (!state.configured) {
        throw error("call window(title, width, height) before creating graphics");
    }
    if (state.shown) {
        throw error("graphics commands cannot be added after show()");
    }
}

static const std::string& asString(const Argument& argument, const std::string& name) {
    const auto* value = std::get_if<std::string>(&argument);
    if (value == nullptr) {
        throw error(name + " must be a string");
    }
    return *value;
}

static double asNumber(const Argument& argument, const std::string& name) {
    double value = 0.0;
    if (const auto* integer = std::get_if<std::int64_t>(&argument)) {
        value = static_cast<double>(*integer);
    } else if (const auto* floating = std::get_if<double>(&argument)) {
        value = *floating;
    } else {
        throw error(name + " must be a number");
    }
    if (!std::isfinite(value) || std::fabs(value) > 10000000.0) {
        throw error(name + " is outside the supported range");
    }
    return value;
}

static unsigned int asPositiveInteger(const Argument& argument, const std::string& name,
                                      unsigned int maximum) {
    const double value = asNumber(argument, name);
    if (value < 1.0 || value > maximum || std::floor(value) != value) {
        throw error(name + " must be a whole number from 1 to " +
                    std::to_string(maximum));
    }
    return static_cast<unsigned int>(value);
}

static unsigned int parseHexByte(const std::string& text, std::size_t offset) {
    unsigned int value = 0;
    for (std::size_t i = offset; i < offset + 2; ++i) {
        const char c = text[i];
        unsigned int digit = 0;
        if (c >= '0' && c <= '9') digit = static_cast<unsigned int>(c - '0');
        else if (c >= 'a' && c <= 'f') digit = static_cast<unsigned int>(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') digit = static_cast<unsigned int>(c - 'A' + 10);
        else throw error("invalid hexadecimal color '" + text + "'");
        value = value * 16 + digit;
    }
    return value;
}

static Color parseColor(const std::string& input) {
    static const std::unordered_map<std::string, Color> namedColors{
        {"black", {0.0F, 0.0F, 0.0F, 1.0F}},
        {"white", {1.0F, 1.0F, 1.0F, 1.0F}},
        {"red", {1.0F, 0.0F, 0.0F, 1.0F}},
        {"green", {0.0F, 0.5F, 0.0F, 1.0F}},
        {"blue", {0.0F, 0.0F, 1.0F, 1.0F}},
        {"yellow", {1.0F, 1.0F, 0.0F, 1.0F}},
        {"cyan", {0.0F, 1.0F, 1.0F, 1.0F}},
        {"magenta", {1.0F, 0.0F, 1.0F, 1.0F}},
        {"orange", {1.0F, 0.647F, 0.0F, 1.0F}},
        {"purple", {0.5F, 0.0F, 0.5F, 1.0F}},
        {"pink", {1.0F, 0.753F, 0.796F, 1.0F}},
        {"gray", {0.5F, 0.5F, 0.5F, 1.0F}},
        {"grey", {0.5F, 0.5F, 0.5F, 1.0F}},
        {"transparent", {0.0F, 0.0F, 0.0F, 0.0F}}
    };

    const auto named = namedColors.find(input);
    if (named != namedColors.end()) return named->second;
    if (input.size() != 4 && input.size() != 7 && input.size() != 9) {
        throw error("color must be a named color or #RGB, #RRGGBB, or #RRGGBBAA");
    }
    if (input.front() != '#') {
        throw error("color must be a named color or #RGB, #RRGGBB, or #RRGGBBAA");
    }

    if (input.size() == 4) {
        Color color{};
        float* channels[] = {&color.red, &color.green, &color.blue};
        for (std::size_t i = 0; i < 3; ++i) {
            const std::string pair(2, input[i + 1]);
            *channels[i] = static_cast<float>(parseHexByte(pair, 0)) / 255.0F;
        }
        color.alpha = 1.0F;
        return color;
    }
    Color color{
        static_cast<float>(parseHexByte(input, 1)) / 255.0F,
        static_cast<float>(parseHexByte(input, 3)) / 255.0F,
        static_cast<float>(parseHexByte(input, 5)) / 255.0F,
        1.0F
    };
    if (input.size() == 9) {
        color.alpha = static_cast<float>(parseHexByte(input, 7)) / 255.0F;
    }
    return color;
}

static std::string lowercase(std::string value) {
    for (char& character : value) {
        if (character >= 'A' && character <= 'Z') {
            character = static_cast<char>(character - 'A' + 'a');
        }
    }
    return value;
}

static Color colorFromArgument(const Argument& value) {
    return parseColor(asString(value, "color"));
}

static Point convertPoint(double x, double y) {
    if (state.normalizedCoordinates) {
        return {static_cast<float>(x * state.width),
                static_cast<float>(y * state.height)};
    }
    if (state.centerCoordinates) {
        return {static_cast<float>(state.width / 2.0 + x),
                static_cast<float>(state.height / 2.0 - y)};
    }
    return {static_cast<float>(x), static_cast<float>(y)};
}

static void convertRectangle(double x, double y, double width, double height,
                             float& outputX, float& outputY,
                             float& outputWidth, float& outputHeight) {
    if (state.normalizedCoordinates) {
        outputX = static_cast<float>(x * state.width);
        outputY = static_cast<float>(y * state.height);
        outputWidth = static_cast<float>(width * state.width);
        outputHeight = static_cast<float>(height * state.height);
    } else if (state.centerCoordinates) {
        outputX = static_cast<float>(state.width / 2.0 + x);
        outputY = static_cast<float>(state.height / 2.0 - y - height);
        outputWidth = static_cast<float>(width);
        outputHeight = static_cast<float>(height);
    } else {
        outputX = static_cast<float>(x);
        outputY = static_cast<float>(y);
        outputWidth = static_cast<float>(width);
        outputHeight = static_cast<float>(height);
    }
}

#ifdef _WIN32

static std::wstring toWide(const std::string& text) {
    if (text.empty()) return {};
    if (text.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        throw error("text is too long");
    }
    const int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                                         static_cast<int>(text.size()), nullptr, 0);
    if (size <= 0) throw error("text is not valid UTF-8");
    std::wstring result(static_cast<std::size_t>(size), L'\0');
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(),
                            static_cast<int>(text.size()), result.data(), size) == 0) {
        throw error("failed to decode text");
    }
    return result;
}

static std::string toUtf8(const std::wstring& text) {
    if (text.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(),
                                         static_cast<int>(text.size()), nullptr, 0,
                                         nullptr, nullptr);
    if (size <= 0) throw error("failed to encode input as UTF-8");
    std::string result(static_cast<std::size_t>(size), '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(),
                            static_cast<int>(text.size()), result.data(), size,
                            nullptr, nullptr) <= 0) {
        throw error("failed to encode input as UTF-8");
    }
    return result;
}

struct InputDialogState {
    std::wstring prompt;
    std::wstring result;
    HWND edit = nullptr;
    bool accepted = false;
};

static LRESULT CALLBACK inputDialogProcedure(HWND window, UINT message,
                                             WPARAM wParam, LPARAM lParam) {
    if (message == WM_NCCREATE) {
        const auto* create = reinterpret_cast<const CREATESTRUCTW*>(lParam);
        SetWindowLongPtrW(window, GWLP_USERDATA,
                          reinterpret_cast<LONG_PTR>(create->lpCreateParams));
    }
    auto* dialog = reinterpret_cast<InputDialogState*>(
        GetWindowLongPtrW(window, GWLP_USERDATA));
    if (message == WM_CREATE && dialog != nullptr) {
        const HWND prompt = CreateWindowExW(
            0, L"STATIC", dialog->prompt.c_str(), WS_CHILD | WS_VISIBLE,
            12, 12, 396, 32, window, nullptr, GetModuleHandleW(nullptr), nullptr);
        dialog->edit = CreateWindowExW(
            WS_EX_CLIENTEDGE, L"EDIT", L"",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
            12, 48, 396, 26, window, reinterpret_cast<HMENU>(1001),
            GetModuleHandleW(nullptr), nullptr);
        const HWND accept = CreateWindowExW(
            0, L"BUTTON", L"OK",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
            236, 88, 80, 28, window, reinterpret_cast<HMENU>(IDOK),
            GetModuleHandleW(nullptr), nullptr);
        const HWND cancel = CreateWindowExW(
            0, L"BUTTON", L"Cancel", WS_CHILD | WS_VISIBLE | WS_TABSTOP,
            328, 88, 80, 28, window, reinterpret_cast<HMENU>(IDCANCEL),
            GetModuleHandleW(nullptr), nullptr);
        if (prompt == nullptr || dialog->edit == nullptr ||
            accept == nullptr || cancel == nullptr) {
            return -1;
        }
        SendMessageW(dialog->edit, EM_SETLIMITTEXT, 4096, 0);
        return 0;
    }
    if (message == WM_COMMAND && dialog != nullptr) {
        if (LOWORD(wParam) == IDOK && dialog->edit != nullptr) {
            const int length = GetWindowTextLengthW(dialog->edit);
            std::wstring result(static_cast<std::size_t>(length) + 1, L'\0');
            if (length != 0 &&
                GetWindowTextW(dialog->edit, result.data(), length + 1) == 0) {
                return 0;
            }
            result.resize(static_cast<std::size_t>(length));
            dialog->result = std::move(result);
            dialog->accepted = true;
            DestroyWindow(window);
            return 0;
        }
        if (LOWORD(wParam) == IDCANCEL) {
            dialog->accepted = false;
            DestroyWindow(window);
            return 0;
        }
    }
    if (message == WM_CLOSE) {
        if (dialog != nullptr) dialog->accepted = false;
        DestroyWindow(window);
        return 0;
    }
    return DefWindowProcW(window, message, wParam, lParam);
}

static std::string showInputDialog(const std::string& prompt) {
    static const wchar_t className[] = L"ViLangOpenGLInputDialog";
    static bool classRegistered = false;
    HINSTANCE instance = GetModuleHandleW(nullptr);
    if (!classRegistered) {
        WNDCLASSEXW windowClass{};
        windowClass.cbSize = sizeof(windowClass);
        windowClass.lpfnWndProc = inputDialogProcedure;
        windowClass.hInstance = instance;
        windowClass.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
        windowClass.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
        windowClass.lpszClassName = className;
        if (!RegisterClassExW(&windowClass) &&
            GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
            throw error("failed to register graphical input dialog");
        }
        classRegistered = true;
    }

    InputDialogState dialog{toWide(prompt), {}, nullptr, false};
    const int width = 432;
    const int height = 156;
    int x = CW_USEDEFAULT;
    int y = CW_USEDEFAULT;
    if (state.window != nullptr) {
        RECT owner{};
        if (GetWindowRect(state.window, &owner)) {
            x = owner.left + ((owner.right - owner.left) - width) / 2;
            y = owner.top + ((owner.bottom - owner.top) - height) / 2;
        }
        EnableWindow(state.window, FALSE);
    }
    HWND window = CreateWindowExW(
        WS_EX_DLGMODALFRAME | WS_EX_CONTROLPARENT, className,
        L"ViLang input", WS_CAPTION | WS_SYSMENU | WS_POPUP,
        x, y, width, height, state.window, nullptr, instance, &dialog);
    if (window == nullptr) {
        if (state.window != nullptr) EnableWindow(state.window, TRUE);
        throw error("failed to create graphical input dialog");
    }
    ShowWindow(window, SW_SHOW);
    UpdateWindow(window);
    SetForegroundWindow(window);
    SetFocus(dialog.edit);

    MSG message{};
    while (IsWindow(window)) {
        const BOOL status = GetMessageW(&message, nullptr, 0, 0);
        if (status == -1) {
            DestroyWindow(window);
            if (state.window != nullptr) EnableWindow(state.window, TRUE);
            throw error("failed to read graphical input events");
        }
        if (status == 0) {
            PostQuitMessage(static_cast<int>(message.wParam));
            break;
        }
        if (!IsDialogMessageW(window, &message)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        if (IsWindow(window)) DestroyWindow(window);
    }
    if (state.window != nullptr) {
        EnableWindow(state.window, TRUE);
        SetForegroundWindow(state.window);
    }
    if (!dialog.accepted) return {};
    return toUtf8(dialog.result);
}

static void setColor(const Color& color) {
    glColor4f(color.red, color.green, color.blue, color.alpha);
}

static void drawRoundedRectangle(float x, float y, float width, float height,
                                 float radius, const Color& color) {
    const float r = std::max(0.0F, std::min(radius, std::min(width, height) / 2.0F));
    if (r <= 0.0F) {
        setColor(color);
        glBegin(GL_QUADS);
        glVertex2f(x, y);
        glVertex2f(x + width, y);
        glVertex2f(x + width, y + height);
        glVertex2f(x, y + height);
        glEnd();
        return;
    }

    constexpr int segments = 10;
    const float centersX[] = {x + width - r, x + width - r, x + r, x + r};
    const float centersY[] = {y + r, y + height - r, y + height - r, y + r};
    const float startAngles[] = {-90.0F, 0.0F, 90.0F, 180.0F};
    setColor(color);
    glBegin(GL_TRIANGLE_FAN);
    glVertex2f(x + width / 2.0F, y + height / 2.0F);
    for (int corner = 0; corner < 4; ++corner) {
        for (int segment = 0; segment <= segments; ++segment) {
            const float angle = (startAngles[corner] +
                                 90.0F * static_cast<float>(segment) / segments) *
                                0.01745329251994329577F;
            glVertex2f(centersX[corner] + std::cos(angle) * r,
                       centersY[corner] + std::sin(angle) * r);
        }
    }
    glVertex2f(x + width, y + r);
    glEnd();
}

static void drawCircle(float centerX, float centerY, float radius, const Color& color) {
    setColor(color);
    glBegin(GL_TRIANGLE_FAN);
    glVertex2f(centerX, centerY);
    constexpr int segments = 64;
    for (int i = 0; i <= segments; ++i) {
        const float angle = 6.2831853071795864769F * static_cast<float>(i) / segments;
        glVertex2f(centerX + std::cos(angle) * radius,
                   centerY + std::sin(angle) * radius);
    }
    glEnd();
}

static void drawText(const std::string& text, float x, float y, unsigned int size,
                     const Color& color) {
    if (state.font == nullptr || state.fontLists == 0) return;
    HGDIOBJ oldFont = SelectObject(state.deviceContext, state.font);
    HFONT font = CreateFontW(-static_cast<int>(size), 0, 0, 0, FW_NORMAL, FALSE, FALSE,
                             FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                             CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY,
                             DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
    if (font != nullptr) {
        SelectObject(state.deviceContext, font);
        wglUseFontBitmapsW(state.deviceContext, 32, 95, state.fontLists + 32);
        wglUseFontBitmapsW(state.deviceContext, 1024, 256, state.fontLists + 1024);
        SelectObject(state.deviceContext, state.font);
        DeleteObject(font);
    }
    if (oldFont != nullptr) SelectObject(state.deviceContext, oldFont);

    const std::wstring wide = toWide(text);
    if (wide.empty()) return;
    setColor(color);
    glRasterPos2f(x, y + static_cast<float>(size));
    glListBase(state.fontLists);
    glCallLists(static_cast<GLsizei>(wide.size()), GL_UNSIGNED_SHORT, wide.data());
}

static Color buttonColor(const Color& color, bool hovered, bool clicked) {
    const float factor = clicked ? 0.72F : (hovered ? 1.18F : 1.0F);
    return {std::min(color.red * factor, 1.0F),
            std::min(color.green * factor, 1.0F),
            std::min(color.blue * factor, 1.0F),
            color.alpha};
}

static void render() {
    glViewport(0, 0, state.width, state.height);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glOrtho(0.0, state.width, state.height, 0.0, -1.0, 1.0);
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    glClearColor(state.background.red, state.background.green,
                 state.background.blue, state.background.alpha);
    glClear(GL_COLOR_BUFFER_BIT);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    for (std::size_t i = 0; i < state.shapes.size(); ++i) {
        const Shape& shape = state.shapes[i];
        switch (shape.type) {
        case ShapeType::Rectangle:
            drawRoundedRectangle(shape.x, shape.y, shape.width, shape.height,
                                 0.0F, shape.color);
            break;
        case ShapeType::RoundedRectangle:
            drawRoundedRectangle(shape.x, shape.y, shape.width, shape.height,
                                 shape.radius, shape.color);
            break;
        case ShapeType::Circle:
            drawCircle(shape.x, shape.y, shape.radius, shape.color);
            break;
        case ShapeType::Ellipse:
            glPushMatrix();
            glTranslatef(shape.x, shape.y, 0.0F);
            glScalef(shape.width, shape.height, 1.0F);
            drawCircle(0.0F, 0.0F, 1.0F, shape.color);
            glPopMatrix();
            break;
        case ShapeType::Line:
            setColor(shape.color);
            glLineWidth(shape.strokeWidth);
            glBegin(GL_LINES);
            glVertex2f(shape.x, shape.y);
            glVertex2f(shape.width, shape.height);
            glEnd();
            break;
        case ShapeType::Text:
            drawText(shape.text, shape.x, shape.y, shape.fontSize, shape.color);
            break;
        case ShapeType::Button: {
            const bool hovered = state.hoveredButton == i;
            const bool clicked = state.buttonClicked && hovered;
            drawRoundedRectangle(shape.x, shape.y, shape.width, shape.height,
                                 shape.radius, buttonColor(shape.color, hovered, clicked));
            const std::wstring label = toWide(shape.text);
            SIZE textSize{};
            if (state.font != nullptr) {
                HGDIOBJ oldFont = SelectObject(state.deviceContext, state.font);
                GetTextExtentPoint32W(state.deviceContext, label.c_str(),
                                      static_cast<int>(label.size()), &textSize);
                if (oldFont != nullptr) SelectObject(state.deviceContext, oldFont);
            }
            const float textX = shape.x + (shape.width - textSize.cx) / 2.0F;
            const float textY = shape.y + (shape.height - shape.fontSize) / 2.0F;
            drawText(shape.text, textX, textY, shape.fontSize,
                     {1.0F, 1.0F, 1.0F, 1.0F});
            break;
        }
        }
    }
    glFlush();
}

static LRESULT CALLBACK windowProcedure(HWND window, UINT message,
                                        WPARAM wParam, LPARAM lParam) {
    if (message == WM_NCCREATE) {
        const auto* create = reinterpret_cast<const CREATESTRUCTW*>(lParam);
        SetWindowLongPtrW(window, GWLP_USERDATA,
                          reinterpret_cast<LONG_PTR>(create->lpCreateParams));
    }
    switch (message) {
    case WM_ERASEBKGND:
        return 1;
    case WM_SIZE:
        state.width = std::max(1, static_cast<int>(LOWORD(lParam)));
        state.height = std::max(1, static_cast<int>(HIWORD(lParam)));
        InvalidateRect(window, nullptr, FALSE);
        return 0;
    case WM_MOUSEMOVE: {
        const float x = static_cast<float>(GET_X_LPARAM(lParam));
        const float y = static_cast<float>(GET_Y_LPARAM(lParam));
        std::size_t hovered = std::numeric_limits<std::size_t>::max();
        for (std::size_t i = 0; i < state.shapes.size(); ++i) {
            const Shape& shape = state.shapes[i];
            if (shape.type == ShapeType::Button && x >= shape.x &&
                x <= shape.x + shape.width && y >= shape.y &&
                y <= shape.y + shape.height) {
                hovered = i;
            }
        }
        if (hovered != state.hoveredButton) {
            state.hoveredButton = hovered;
            InvalidateRect(window, nullptr, FALSE);
        }
        return 0;
    }
    case WM_LBUTTONDOWN: {
        const float x = static_cast<float>(GET_X_LPARAM(lParam));
        const float y = static_cast<float>(GET_Y_LPARAM(lParam));
        for (std::size_t i = 0; i < state.shapes.size(); ++i) {
            const Shape& shape = state.shapes[i];
            if (shape.type == ShapeType::Button && x >= shape.x &&
                x <= shape.x + shape.width && y >= shape.y &&
                y <= shape.y + shape.height) {
                state.hoveredButton = i;
                state.buttonClicked = true;
                std::cout << "Button clicked: " << shape.text << '\n';
                InvalidateRect(window, nullptr, FALSE);
            }
        }
        return 0;
    }
    case WM_LBUTTONUP:
        state.buttonClicked = false;
        InvalidateRect(window, nullptr, FALSE);
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT paint{};
        BeginPaint(window, &paint);
        if (state.renderContext != nullptr &&
            wglMakeCurrent(state.deviceContext, state.renderContext)) {
            render();
            SwapBuffers(state.deviceContext);
        }
        EndPaint(window, &paint);
        return 0;
    }
    case WM_CLOSE:
        DestroyWindow(window);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    default:
        return DefWindowProcW(window, message, wParam, lParam);
    }
}

static void showWindow() {
    if (!state.configured) {
        throw error("call window(title, width, height) before show()");
    }
    if (state.shown) throw error("show() can only be called once");
    state.shown = true;

    static const wchar_t className[] = L"ViLangOpenGLWindow";
    HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSEXW windowClass{};
    windowClass.cbSize = sizeof(windowClass);
    windowClass.style = CS_OWNDC;
    windowClass.lpfnWndProc = windowProcedure;
    windowClass.hInstance = instance;
    windowClass.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
    windowClass.lpszClassName = className;
    if (!RegisterClassExW(&windowClass) &&
        GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
        throw error("failed to register window class");
    }

    RECT bounds{0, 0, state.width, state.height};
    if (!AdjustWindowRect(&bounds, WS_OVERLAPPEDWINDOW, FALSE)) {
        throw error("failed to calculate window size");
    }
    const std::wstring title = toWide(state.title);
    state.window = CreateWindowExW(
        0, className, title.c_str(), WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT, CW_USEDEFAULT, bounds.right - bounds.left,
        bounds.bottom - bounds.top, nullptr, nullptr, instance, &state);
    if (state.window == nullptr) throw error("failed to create window");

    state.deviceContext = GetDC(state.window);
    if (state.deviceContext == nullptr) throw error("failed to acquire window drawing context");
    PIXELFORMATDESCRIPTOR pixelFormat{};
    pixelFormat.nSize = sizeof(pixelFormat);
    pixelFormat.nVersion = 1;
    pixelFormat.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
    pixelFormat.iPixelType = PFD_TYPE_RGBA;
    pixelFormat.cColorBits = 32;
    pixelFormat.cAlphaBits = 8;
    pixelFormat.cDepthBits = 0;
    pixelFormat.iLayerType = PFD_MAIN_PLANE;
    const int format = ChoosePixelFormat(state.deviceContext, &pixelFormat);
    if (format == 0 || !SetPixelFormat(state.deviceContext, format, &pixelFormat)) {
        throw error("failed to select an OpenGL pixel format");
    }

    state.renderContext = wglCreateContext(state.deviceContext);
    if (state.renderContext == nullptr ||
        !wglMakeCurrent(state.deviceContext, state.renderContext)) {
        throw error("failed to create an OpenGL context");
    }

    state.font = CreateFontW(-18, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                             DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                             ANTIALIASED_QUALITY, DEFAULT_PITCH | FF_DONTCARE,
                             L"Segoe UI");
    state.fontLists = glGenLists(1280);
    if (state.font == nullptr || state.fontLists == 0) {
        throw error("failed to initialize OpenGL text rendering");
    }
    HGDIOBJ oldFont = SelectObject(state.deviceContext, state.font);
    if (!wglUseFontBitmapsW(state.deviceContext, 32, 95, state.fontLists + 32) ||
        !wglUseFontBitmapsW(state.deviceContext, 1024, 256, state.fontLists + 1024)) {
        if (oldFont != nullptr) SelectObject(state.deviceContext, oldFont);
        throw error("failed to create OpenGL font glyphs");
    }
    if (oldFont != nullptr) SelectObject(state.deviceContext, oldFont);

    ShowWindow(state.window, SW_SHOW);
    UpdateWindow(state.window);

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }

    if (state.renderContext != nullptr) {
        wglMakeCurrent(nullptr, nullptr);
        wglDeleteContext(state.renderContext);
        state.renderContext = nullptr;
    }
    if (state.deviceContext != nullptr && state.window != nullptr) {
        ReleaseDC(state.window, state.deviceContext);
        state.deviceContext = nullptr;
    }
    if (state.font != nullptr) {
        DeleteObject(state.font);
        state.font = nullptr;
    }
    if (state.window != nullptr) {
        state.window = nullptr;
    }
}

#else

static std::string showInputDialog(const std::string&) {
    throw error("graphical input is currently supported on Windows only");
}

static void showWindow() {
    throw error("OpenGL windows are currently supported on Windows only");
}

#endif

static Argument call(const std::string& requestedName,
                     const std::vector<Argument>& arguments) {
    const std::string name = lowercase(requestedName);
    if (name == "gpu_input" || name == "input_box") {
        requireArity(name, arguments, 1);
        return showInputDialog(asString(arguments[0], "input prompt"));
    }
    if (name == "window") {
        requireArity(name, arguments, 3);
        if (state.configured) throw error("window() can only be called once");
        state.title = asString(arguments[0], "window title");
        state.width = static_cast<int>(asPositiveInteger(arguments[1], "window width", 8192));
        state.height = static_cast<int>(asPositiveInteger(arguments[2], "window height", 8192));
        state.configured = true;
        return std::monostate{};
    }
    if (name == "coordinates") {
        requireArity(name, arguments, 1);
        requireConfigured();
        const std::string mode = lowercase(asString(arguments[0], "coordinate mode"));
        if (mode == "pixels" || mode == "pixel") {
            state.normalizedCoordinates = false;
            state.centerCoordinates = false;
        } else if (mode == "normalized" || mode == "relative") {
            state.normalizedCoordinates = true;
            state.centerCoordinates = false;
        } else if (mode == "center") {
            state.normalizedCoordinates = false;
            state.centerCoordinates = true;
        } else {
            throw error("coordinate mode must be pixels, normalized, or center");
        }
        return std::monostate{};
    }
    if (name == "background") {
        requireArity(name, arguments, 1);
        requireConfigured();
        state.background = colorFromArgument(arguments[0]);
        return std::monostate{};
    }
    if (name == "show" || name == "run") {
        requireArity(name, arguments, 0);
        showWindow();
        return std::monostate{};
    }

    requireConfigured();
    Shape shape{};
    if (name == "rect" || name == "rectangle" || name == "rounded_rect" ||
        name == "rounded_rectangle") {
        const bool rounded = name == "rounded_rect" || name == "rounded_rectangle";
        requireArity(name, arguments, rounded ? 6 : 5);
        convertRectangle(asNumber(arguments[0], "x"), asNumber(arguments[1], "y"),
                         asNumber(arguments[2], "width"), asNumber(arguments[3], "height"),
                         shape.x, shape.y, shape.width, shape.height);
        if (shape.width <= 0.0F || shape.height <= 0.0F) {
            throw error("rectangle width and height must be positive");
        }
        shape.type = rounded ? ShapeType::RoundedRectangle : ShapeType::Rectangle;
        if (rounded) {
            const double radius = asNumber(arguments[4], "corner radius");
            if (radius < 0.0) throw error("corner radius cannot be negative");
            shape.radius = static_cast<float>(
                state.normalizedCoordinates ? radius * std::min(state.width, state.height)
                : radius);
            shape.color = colorFromArgument(arguments[5]);
        } else {
            shape.color = colorFromArgument(arguments[4]);
        }
    } else if (name == "circle") {
        requireArity(name, arguments, 4);
        const Point center = convertPoint(asNumber(arguments[0], "x"),
                                          asNumber(arguments[1], "y"));
        const double radius = asNumber(arguments[2], "radius");
        if (radius <= 0.0) throw error("circle radius must be positive");
        shape.type = ShapeType::Circle;
        shape.x = center.x;
        shape.y = center.y;
        shape.radius = static_cast<float>(
            state.normalizedCoordinates ? radius * std::min(state.width, state.height)
            : radius);
        shape.color = colorFromArgument(arguments[3]);
    } else if (name == "ellipse") {
        requireArity(name, arguments, 5);
        const Point center = convertPoint(asNumber(arguments[0], "x"),
                                          asNumber(arguments[1], "y"));
        const double radiusX = asNumber(arguments[2], "horizontal radius");
        const double radiusY = asNumber(arguments[3], "vertical radius");
        if (radiusX <= 0.0 || radiusY <= 0.0) {
            throw error("ellipse radii must be positive");
        }
        shape.type = ShapeType::Ellipse;
        shape.x = center.x;
        shape.y = center.y;
        shape.width = static_cast<float>(state.normalizedCoordinates
                                             ? radiusX * state.width
                                             : radiusX);
        shape.height = static_cast<float>(state.normalizedCoordinates
                                              ? radiusY * state.height
                                              : radiusY);
        shape.color = colorFromArgument(arguments[4]);
    } else if (name == "line") {
        requireArity(name, arguments, 6);
        const Point first = convertPoint(asNumber(arguments[0], "x1"),
                                         asNumber(arguments[1], "y1"));
        const Point second = convertPoint(asNumber(arguments[2], "x2"),
                                          asNumber(arguments[3], "y2"));
        const double width = asNumber(arguments[5], "line width");
        if (width <= 0.0 || width > 256.0) {
            throw error("line width must be greater than 0 and at most 256");
        }
        shape.type = ShapeType::Line;
        shape.x = first.x;
        shape.y = first.y;
        shape.width = second.x;
        shape.height = second.y;
        shape.strokeWidth = static_cast<float>(width);
        shape.color = colorFromArgument(arguments[4]);
    } else if (name == "text") {
        requireArity(name, arguments, 5);
        const Point position = convertPoint(asNumber(arguments[1], "x"),
                                            asNumber(arguments[2], "y"));
        shape.type = ShapeType::Text;
        shape.text = asString(arguments[0], "text");
        shape.x = position.x;
        shape.y = position.y;
        shape.color = colorFromArgument(arguments[3]);
        shape.fontSize = asPositiveInteger(arguments[4], "font size", 256);
    } else if (name == "button") {
        requireArity(name, arguments, 7);
        convertRectangle(asNumber(arguments[1], "x"), asNumber(arguments[2], "y"),
                         asNumber(arguments[3], "width"), asNumber(arguments[4], "height"),
                         shape.x, shape.y, shape.width, shape.height);
        const double radius = asNumber(arguments[6], "corner radius");
        if (shape.width <= 0.0F || shape.height <= 0.0F || radius < 0.0) {
            throw error("button size must be positive and corner radius non-negative");
        }
        shape.type = ShapeType::Button;
        shape.text = asString(arguments[0], "button text");
        shape.radius = static_cast<float>(
            state.normalizedCoordinates ? radius * std::min(state.width, state.height)
            : radius);
        shape.color = colorFromArgument(arguments[5]);
    } else {
        throw error("unknown function '" + requestedName + "'");
    }

    state.shapes.push_back(std::move(shape));
    return std::monostate{};
}

} // namespace vilang::gpu