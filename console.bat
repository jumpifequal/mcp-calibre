@echo off
rem Launches the calibre-mcp console (no terminal window).
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0gui\calibre_mcp_console.py"
    goto :eof
)
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw -3 "%~dp0gui\calibre_mcp_console.py"
    goto :eof
)
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%~dp0gui\calibre_mcp_console.py"
    goto :eof
)
echo [!] No Python found. Run setup-wizard.bat first, or install Python 3.10+ from python.org.
pause
