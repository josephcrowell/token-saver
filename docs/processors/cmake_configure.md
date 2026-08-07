# CMake Configure Processor

Compresses output from CMake's configuration phase. Recognized commands:

- `cmake -B build -S .`
- `cmake -G Ninja -B build`
- `cmake -DCMAKE_BUILD_TYPE=Debug ...`
- `cmake -DCMAKE_TOOLCHAIN_FILE=... -B build`

The build phase (`cmake --build`) is handled by the C/C++ build processor.
`cmake --install` is handled by the CMake install processor.

## What it compresses

- `Detecting C/C++ compiler ABI info`, `Detecting C compile features`
- `Performing Test CMAKE_HAVE_LIBC_PTHREAD`, etc.
- `Found PkgConfig`, `Found Threads`, etc.
- `-- The CXX compiler identification is GNU …`
- Routine `-- Looking for X`, `-- Checking for module 'X'`

## What it preserves

- `-- Package 'X' not found` (missing dependency diagnostics)
- `Detected:` lines (`-- Build files have been written to: …`)
- `CMake Error at <file>:<line> (<func>):` with indented continuation
- `-- Configuring incomplete, errors occurred!` summary
- `CMake Warning` lines

## Example

Input (12-line configure output):

```
-- The C compiler identification is GNU 14.2.1
-- The CXX compiler identification is GNU 14.2.1
-- Detecting C/C++ compiler ABI info
-- Detecting C compile features
-- Performing Test CMAKE_HAVE_LIBC_PTHREAD
-- Performing Test CMAKE_HAVE_LIBC_PTHREAD - Success
-- Found PkgConfig: /usr/bin/pkg-config
-- Checking for module 'systemd'
--   Package 'systemd' not found
-- Configuring done
-- Generating done
-- Build files have been written to: /home/joseph/Project/build
```

Output:

```
CMake configure: 5 checks (detecting=2, performing=2, found=1)
Not found:
  --   Package 'systemd' not found
Detected:
  -- Build files have been written to: /home/joseph/Project/build
-- Configuring done
-- Generating done
```
