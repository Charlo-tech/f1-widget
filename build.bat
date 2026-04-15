@echo off
REM =========================================================
REM  F1 Desktop Widget — One-Click Build Script
REM
REM  Produces:
REM    dist\F1Widget\F1Widget.exe        (portable folder)
REM    installer_output\F1Widget_Setup.exe  (installer, needs Inno Setup)
REM
REM  If EXE crashes with "no module" errors, run in debug mode:
REM    pyinstaller f1_widget.spec --noconfirm  (change console=True in spec first)
REM =========================================================

echo.
echo  =============================================
echo   F1 Desktop Widget - Build Tool
echo  =============================================
echo.

REM ── Activate venv ─────────────────────────────────────────
if not exist venv\Scripts\activate.bat (
    echo [ERROR] No virtual environment found.
    echo         Run: python -m venv venv
    echo               venv\Scripts\activate
    echo               pip install -r requirements.txt
    pause & exit /b 1
)
call venv\Scripts\activate.bat
echo [OK] Virtual environment activated

REM ── PyInstaller ───────────────────────────────────────────
echo [..] Installing/updating PyInstaller...
pip install pyinstaller --quiet --upgrade
echo [OK] PyInstaller ready

REM ── Clean ─────────────────────────────────────────────────
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist
echo [OK] Previous build cleaned

REM ── Build ─────────────────────────────────────────────────
echo [..] Building EXE (this takes 2-4 minutes)...
pyinstaller f1_widget.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed.
    echo         Try running manually for more detail:
    echo           pyinstaller f1_widget.spec --noconfirm --log-level DEBUG
    pause & exit /b 1
)
echo [OK] EXE built: dist\F1Widget\F1Widget.exe

REM ── Inno Setup ────────────────────────────────────────────
set INNO1="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set INNO2="C:\Program Files\Inno Setup 6\ISCC.exe"
set INNO=

if exist %INNO1% set INNO=%INNO1%
if exist %INNO2% set INNO=%INNO2%

if defined INNO (
    echo [..] Building installer...
    if not exist installer_output mkdir installer_output
    %INNO% installer.iss
    if errorlevel 1 (
        echo [WARN] Inno Setup failed. Portable EXE still available.
    ) else (
        echo [OK] Installer: installer_output\F1Widget_Setup.exe
    )
) else (
    echo [WARN] Inno Setup 6 not found - skipping installer.
    echo        Download: https://jrsoftware.org/isinfo.php
)

echo.
echo  =============================================
echo   BUILD COMPLETE
echo  =============================================
echo   Portable:   dist\F1Widget\F1Widget.exe
if exist installer_output\F1Widget_Setup.exe (
echo   Installer:  installer_output\F1Widget_Setup.exe
)
echo.
echo   TIP: If the EXE crashes on launch, open f1_widget.spec,
echo        change console=False to console=True, rebuild,
echo        then run the EXE from a terminal to see the error.
echo.
pause
