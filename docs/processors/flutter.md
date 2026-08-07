# Flutter / Dart Processor

Compresses output from `flutter` and `dart` commands:

- `flutter build apk|aab|ios|macos|linux|web|windows`
- `flutter run`
- `flutter test`
- `flutter pub get|deps|outdated|upgrade|run`
- `flutter analyze`
- `flutter doctor [-v]`
- `flutter clean|precache|assemble|format|fix|screenshot|driver`
- `dart run|analyze|test|compile|pub|fmt|fix`

## What it compresses

- Gradle/Xcode/CocoaPods progress lines and `[N/M]` task output
- Pub dependency-resolution chatter and per-package download progress
- Asset compilation and "Built …" repeats
- Doctor preamble, version banners
- Analyzers' "Analyzing …" banner and "No issues found" padding

## What it preserves

- Errors with their `at`, `note:`, `help:` continuations
- File and line locations for analyzer findings
- Final BUILD / analyze / doctor result lines
- Stack frames and exception messages

## Example

Input (35-line `flutter build apk` output):

```
Resolving dependencies...
Got dependencies!
Downloading package_assets 1.0.0
Downloading grdk_plugins 2.0.0
  /root/.pub-cache/...
Built build/ios/iphonesimulator/Runner.app.
✓ Built build/app/outputs/flutter-apk/app-debug.apk
[1/5] Reading build settings for target
[2/5] Copying Cxx source files
[5/5] Linking
Running Gradle task 'assembleRelease'...
Running Xcode build...
FAILURE: Build failed with an exception.
* Where:
File 'lib/main.dart':12:5
lib/main.dart
```

Output:

```
Flutter: 6 progress lines stripped
Running Gradle task 'assembleRelease'...
Running Xcode build...
Errors:
FAILURE: Build failed with an exception.
File 'lib/main.dart':12:5
lib/main.dart
```
