# Packaging and Installation Guide

This document describes how to package, compile, and install `etui` as a native standalone executable for **Linux**, **macOS**, and **Windows**.

---

## 1. External Runtime Prerequisites

`etui` interacts with physical debugger probes and debug clients. Since these tools are external, they must be pre-installed on the host system:

1.  **LLDB:** Required for the interactive LLDB dashboard tab. `etui` runs `lldb` via subprocess.
    *   **Linux:** `sudo apt install lldb`
    *   **macOS:** Installed automatically with Xcode command line tools (`xcode-select --install`).
    *   **Windows:** Installed via standard LLVM distribution installers or package managers like chocolatey (`choco install llvm`).
2.  **OpenOCD / pyOCD:** Required for running gdb servers for debug probes.
3.  **USB Libraries:**
    *   **Linux/macOS:** Depends on `libusb-1.0`.
    *   **Windows:** Relies on USB driver mappings (e.g., WinUSB drivers).

---

## 2. Platform-Specific Build & Installation Instructions

### 2.1 Linux (Ubuntu/Debian/Fedora/etc.)

#### Building from Source:
1.  Install system prerequisites:
    ```bash
    sudo apt-get update
    sudo apt-get install -y libusb-1.0-0-dev python3-dev python3-pip
    ```
2.  Navigate to the project directory and install the packages using `uv` or standard virtualenvs:
    ```bash
    uv pip install pyinstaller
    # or pip install pyinstaller
    ```
3.  Build the standalone binary:
    ```bash
    pyinstaller etui.spec
    ```
    This produces a single-file executable at `dist/etui-linux`.

#### Installation & Setup:
1.  Move the generated binary to your user path:
    ```bash
    sudo mv dist/etui-linux /usr/local/bin/etui
    sudo chmod +x /usr/local/bin/etui
    ```
2.  **USB Probe Permissions Configuration:**
    By default, USB debug adapters (CMSIS-DAP, ST-Link, J-Link, TI XDS110) require root privileges. To allow non-root users access to the debug probes, configure `udev` rules:
    *   Copy the rules file provided by OpenOCD or pyOCD to `/etc/udev/rules.d/`. For example, copy `50-cmsis-dap.rules` to `/etc/udev/rules.d/`.
    *   Reload udev rules:
        ```bash
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        ```

---

### 2.2 macOS

#### Building from Source:
1.  Install Homebrew (if not already present), and download `libusb`:
    ```bash
    brew install libusb
    ```
2.  Build the executable inside your Python environment:
    ```bash
    pip install pyinstaller
    pyinstaller etui.spec
    ```
    This produces `dist/etui-macos`.

#### Installation & Setup:
1.  Move the binary into your PATH:
    ```bash
    mv dist/etui-macos /usr/local/bin/etui
    chmod +x /usr/local/bin/etui
    ```
2.  If macOS Gatekeeper prevents execution because the binary is unsigned, you can sign it locally:
    ```bash
    codesign --force --deep --sign - /usr/local/bin/etui
    ```

---

### 2.3 Windows

#### Building from Source:
1.  Open Command Prompt or PowerShell and navigate to the repository directory.
2.  Ensure you have a C compiler installed (e.g., MSVC from Visual Studio Build Tools) if compiling wheels, though PyInstaller uses precompiled bootloaders.
3.  Install PyInstaller inside your virtual environment:
    ```powershell
    pip install pyinstaller
    ```
4.  Run the build command:
    ```powershell
    pyinstaller etui.spec
    ```
    This generates `dist/etui-windows.exe`.

#### Installation & Setup:
1.  Create a folder such as `C:\bin` and move `etui-windows.exe` into it:
    ```powershell
    mkdir C:\bin
    move dist\etui-windows.exe C:\bin\etui.exe
    ```
2.  Add `C:\bin` to your System's environment `PATH` variable:
    *   Search for "Environment Variables" in Windows Search.
    *   Under System Variables, edit `Path` and append `C:\bin`.
3.  **USB Driver Installation:**
    If pyOCD or OpenOCD fails to connect to the debug probe, download **Zadig** (FOSS driver installer) and replace the current vendor drivers for your debug adapter interface with the `WinUSB` driver.

---

## 3. Automated Builds (CI/CD)

The application has a configured **GitHub Actions** pipeline ([package.yml](file:///home/pawel/src/32bitmicroLLC/EmbeddedTUI/etui/.github/workflows/package.yml)) which automatically builds and releases the binaries.

### How to trigger a build:
1.  Commit and push your changes to your repository.
2.  Create and push a semver release tag:
    ```bash
    git tag v0.1.0
    git push origin v0.1.0
    ```
3.  GitHub Actions will launch native Ubuntu, macOS, and Windows runners to execute the PyInstaller configuration.
4.  Once completed, the workflow will publish a new GitHub Release containing three downloadable artifacts:
    *   `etui-linux` (Linux executable)
    *   `etui-macos` (macOS executable)
    *   `etui-windows.exe` (Windows executable)
