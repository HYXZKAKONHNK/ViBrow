#define main vilang_engine_implementation_main
#include "engine.cpp"
#undef main

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: vilang-vm <bytecode.vbc>\n";
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
        std::cerr << "ViLang VM error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
