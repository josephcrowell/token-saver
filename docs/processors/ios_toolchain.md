# iOS / macOS Toolchain Processor

Compresses output from native Apple-platform tooling:

- `fastlane <lane>` and `bundle exec fastlane <lane>`
- `pod install|update|repo update|search|lib|spec|deintegrate`
- `swift build|test|run|package resolve|package update`
- `xcodebuild -workspace … -scheme …`

## What it compresses

### CocoaPods

- `Analyzing dependencies`, `Downloading dependencies`
- Per-pod `Installing <Pod> (version)` repeats
- Indented `Running pre install hooks`, `Cleaning previous installations`
- `Downloading -> Pod version (size of total)` progress

### fastlane

- Step banners `--- Step: <name>`
- Plain log lines; keeps only the most recent 3 result lines

### Swift Package Manager / build / test

- `Computing version graph`, `Cloning`, `Resolving`, `Checking out`
- `Compiling <module> <file>.swift` repeats
- Individual test result lines (collapses to `n passed, m failed, k skipped`)

### xcodebuild

- `PhaseScriptExecution`, `CompileC`, `Ld …` step lines
- Touching build artifacts

## What it preserves

- `BUILD SUCCEEDED` / `BUILD FAILED` / `TEST SUCCEEDED` markers
- `Pod installation complete!` summary
- `** BUILD FAILED **` / `** TEST SUCCEEDED **`
- `error:` and `warning:` diagnostics with `file:line:col` locations
- `Build complete!` (Swift)
- Test summary: `Executed N tests, with M failures`

## Example (Swift Package build)

Input (10-line build log):

```
Computing version graph
Fetching FromBase64.swift
Resolving Package Graph
Cloning Some/Package
Checking out Some/Package 1.0.0
Compiling MyPackage main.swift
Compiling MyPackage helper.swift
Compiling MyPackage utils.swift
Linking MyPackage
Build complete!
```

Output:

```
Swift: 9 events (compiling=3, computing version=1, fetching=1, resolving=1, cloning=1, checking out=1, linking=1)
Build complete!
```
