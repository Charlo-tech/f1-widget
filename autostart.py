"""
Autostart Manager - Register/unregister the widget to run at system startup.

Supports:
  - Windows:  HKCU registry key
  - macOS:    LaunchAgent plist in ~/Library/LaunchAgents/
  - Linux:    .desktop file in ~/.config/autostart/
"""

import sys
import os
import subprocess
from pathlib import Path


APP_NAME = "F1DesktopWidget"
# Resolve the absolute path to main.py
SCRIPT_DIR = Path(__file__).resolve().parent
MAIN_PY = SCRIPT_DIR / "main.py"
PYTHON_EXE = sys.executable  # Current Python interpreter


class AutostartManager:
    def __init__(self):
        self._platform = sys.platform

    def enable(self):
        if self._platform == "win32":
            self._windows_enable()
        elif self._platform == "darwin":
            self._mac_enable()
        else:
            self._linux_enable()

    def disable(self):
        if self._platform == "win32":
            self._windows_disable()
        elif self._platform == "darwin":
            self._mac_disable()
        else:
            self._linux_disable()

    def is_enabled(self):
        if self._platform == "win32":
            return self._windows_check()
        elif self._platform == "darwin":
            return self._mac_check()
        else:
            return self._linux_check()

    # ── Windows ──────────────────────────────────────────────────────────────

    def _windows_enable(self):
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        cmd = f'"{PYTHON_EXE}" "{MAIN_PY}"'
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        print(f"[Autostart] Windows startup enabled: {cmd}")

    def _windows_disable(self):
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            winreg.DeleteValue(key, APP_NAME)
            winreg.CloseKey(key)
            print("[Autostart] Windows startup disabled.")
        except FileNotFoundError:
            pass

    def _windows_check(self):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ,
            )
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    # ── macOS ─────────────────────────────────────────────────────────────────

    def _plist_path(self):
        return Path.home() / "Library" / "LaunchAgents" / f"com.{APP_NAME.lower()}.plist"

    def _mac_enable(self):
        plist = self._plist_path()
        plist.parent.mkdir(parents=True, exist_ok=True)
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.{APP_NAME.lower()}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON_EXE}</string>
        <string>{MAIN_PY}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.f1widget/widget.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.f1widget/widget.err</string>
</dict>
</plist>
"""
        plist.write_text(content)
        subprocess.run(["launchctl", "load", str(plist)], check=False)
        print(f"[Autostart] macOS LaunchAgent written to {plist}")

    def _mac_disable(self):
        plist = self._plist_path()
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], check=False)
            plist.unlink()
            print("[Autostart] macOS LaunchAgent removed.")

    def _mac_check(self):
        return self._plist_path().exists()

    # ── Linux ────────────────────────────────────────────────────────────────

    def _desktop_path(self):
        return Path.home() / ".config" / "autostart" / f"{APP_NAME.lower()}.desktop"

    def _linux_enable(self):
        desktop = self._desktop_path()
        desktop.parent.mkdir(parents=True, exist_ok=True)
        content = f"""[Desktop Entry]
Type=Application
Name=F1 Desktop Widget
Exec={PYTHON_EXE} {MAIN_PY}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=F1 race data overlay widget
"""
        desktop.write_text(content)
        print(f"[Autostart] Linux .desktop file written to {desktop}")

    def _linux_disable(self):
        path = self._desktop_path()
        if path.exists():
            path.unlink()
            print("[Autostart] Linux .desktop file removed.")

    def _linux_check(self):
        return self._desktop_path().exists()
