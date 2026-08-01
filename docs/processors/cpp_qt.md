# C/C++ and Qt Processors

Token-Saver includes three specialized processors for native and Qt projects.

## Build processor

Recognized commands include GCC, Clang, Ninja, Meson, `cmake --build`, qmake,
moc, uic, and rcc. It removes repetitive progress and target lines while
preserving complete compiler, template-instantiation, linker, CMake, and Qt
autogen failures.

Preserved diagnostics include file/line/column locations, source excerpts,
carets, `note:` and `help:` chains, undefined and duplicate symbols, AUTOMOC,
AUTOUIC, RCC, and qmake project errors.

## Static-analysis processor

Recognized commands include clang-tidy, clang-format, cppcheck,
include-what-you-use/IWYU, qmllint, and qmlformat. Repeated diagnostics are
grouped by rule while retaining representative file locations and messages.

## Test processor

Recognized commands include CTest, GoogleTest-style invocations, Catch2
reporters, Qt Test executables named `tst_*`, and qmltestrunner. Passing cases
are collapsed; failed tests, data rows, actual/expected values, locations, and
final totals remain intact.

As with every processor, compression is applied only when output exceeds the
minimum size and the configured minimum savings ratio.
