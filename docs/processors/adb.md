# ADB Processor

Compresses verbose output from the Android Debug Bridge:

- `adb install [-r|-d|-t|-g]`
- `adb uninstall`
- `adb shell pm list packages [-3]`
- `adb shell pm uninstall`
- `adb shell monkey`
- `adb logcat [-d]`
- `adb pull` / `adb push`
- `adb -s <serial>` invocations

## What it compresses

- Streamed install progress (`[1%] /data/local/tmp/app-debug.apk`)
- Long package lists in `pm list packages` (collapses to count + 5 examples)
- Routine logcat heartbeat lines (counts by level, keeps last 30 + any FATAL block)
- Repeated `adb shell` output

## What it preserves

- `Success` / `Failure [INSTALL_FAILED_*]` install status
- `FATAL EXCEPTION`, `AndroidRuntime`, `java.lang.*` stack frames in logcat
- Uninstallation failures with their `DELETE_FAILED_*` reason
- Per-package install summary in `pm list packages`

## Example

Input (50-package list):

```
package:au.com.example0
package:au.com.example1
...
package:au.com.example49
```

Output:

```
pm list packages: 50 packages
  au.com.example0
  au.com.example1
  au.com.example2
  au.com.example3
  au.com.example4
  ...
  au.com.example45
  au.com.example46
  au.com.example47
  au.com.example48
  au.com.example49
```
