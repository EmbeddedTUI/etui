# Prioritized Issues & Improvements

This document lists bugs, usability bottlenecks, and enhancement suggestions for `etui`, categorized by priority.

---

## 1. High Priority (Bugs & Stability)

### 1.1 Unused Unsafe Decode in `ConsoleTab`
*   **Description:** Inside `ConsoleTab.run_command` ([console.py:L32](file:///home/pawel/src/32bitmicroLLC/EmbeddedTUI/etui/etui/tabs/console.py#L32)), the variable `output = stdout.decode().strip()` is computed but never used. More importantly, calling `decode()` without `errors="replace"` will raise a `UnicodeDecodeError` if a command outputs binary/non-UTF-8 characters.
*   **Impact:** Crashes the execution worker, preventing any further output from printing, including standard error and exit codes.
*   **Fix:** Remove the unused line `output = stdout.decode().strip()`.

### 1.2 Large Files Freeze TUI
*   **Description:** The file viewer ([files.py:L92](file:///home/pawel/src/32bitmicroLLC/EmbeddedTUI/etui/etui/tabs/files.py#L92)) loads entire files via `Syntax.from_path`.
*   **Impact:** For files over a few hundred kilobytes (e.g. log files, binary images), this freezes or severely lags the user interface.
*   **Fix:** Check file size before loading. If the file is larger than 250KB, prompt the user or load only the first few hundred lines.

---

## 2. Medium Priority (Usability & User Experience)

### 2.1 Missing Serial Port Refresh Button
*   **Description:** The serial ports list is loaded only once on mount. If a user plugs in their board after launching `etui`, they cannot select it without restarting the application.
*   **Impact:** Frustrating user experience.
*   **Fix:** Add a "Refresh" button in the serial controls header to re-run `refresh_ports()`.

### 2.2 Standard Input / Command History
*   **Description:** Interactive inputs (e.g. LLDB console, shell commands) do not support history recall (using Up/Down arrow keys).
*   **Impact:** Users must retype commands repeatedly.
*   **Fix:** Implement a history buffer in input panels, intercepting `Key` events to traverse history.

### 2.3 Hardcoded Serial Line Endings
*   **Description:** `SerialTab.send_data` forces `\n` to be appended to outgoing packets.
*   **Impact:** Some microcontrollers only process input terminated with `\r` (CR) or `\r\n` (CRLF).
*   **Fix:** Add a Line Ending selector (Select dropdown) in the serial controls bar with options: `LF (\n)`, `CR (\r)`, `CRLF (\r\n)`, and `None`.

### 2.4 Unimplemented built-in command prefix (`/`)
*   **Description:** The application comments indicate `/` should denote built-in commands (like `/help`, `/exit`, `/clear`), but this is never parsed.
*   **Fix:** Implement simple dispatch logic in `on_input_submitted` within `main.py`.

---

## 3. Low Priority (Features & Refactoring)

### 3.1 Hardcoded Target Selection
*   **Description:** Debugger targets are hardcoded to MSPM0 series.
*   **Fix:** Move target MCU and OpenOCD config mappings into a configuration file (`~/.config/etui/targets.json`) or settings screen.

### 3.2 Dynamic About Panel
*   **Description:** About tab displays hardcoded version text.
*   **Fix:** Read metadata programmatically from `pyproject.toml` (or standard Python package metadata).

### 3.3 Synchronize TUI theme with LLDB Theme
*   **Description:** Changing the LLDB theme does not update the parent Textual app color scheme.
*   **Fix:** Apply the colors defined in selected themes (such as Solarized or Ocean) to Textual's active design system.
