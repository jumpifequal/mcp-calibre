@echo off
rem Starts the calibre-mcp setup wizard (WinForms; runs install.ps1 underneath).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0gui\setup-wizard.ps1"
if errorlevel 1 (
    echo.
    echo [!] The wizard exited with an error. See the message above.
    pause
)
