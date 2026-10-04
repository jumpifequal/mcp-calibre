@echo off
setlocal
set "RC=0"
rem ---------------------------------------------------------------------------
rem  update_embeddings.bat - extract missing texts (OCR for scanned PDFs), refresh the
rem  semantic and figure indexes, then check the result. /? for help.
rem ---------------------------------------------------------------------------

rem Always work from this script's folder (double-click, shortcut or another cwd)
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
set "SERVER=%~dp0calibre_mcp.py"
set "REPORT=%LOCALAPPDATA%\calibre-mcp\embeddings-report.txt"

if /i "%~1"=="/?"     goto :help
if /i "%~1"=="-h"     goto :help
if /i "%~1"=="--help" goto :help

if not exist "%PY%" (
    echo [!] Python environment not found: "%PY%"
    echo     Run install.ps1 first.
    set "RC=1" & goto :end
)
if not exist "%SERVER%" (
    echo [!] calibre_mcp.py not found next to this script.
    set "RC=1" & goto :end
)

echo.
echo [1/4] Missing texts ^(Calibre not indexed yet, scanned PDFs via OCR; failures are remembered^)
"%PY%" "%SERVER%" --extract-missing
if errorlevel 1 (
    echo [!] Text extraction stopped with an error ^(see above^). Continuing.
    set "RC=1"
)

echo.
echo [2/4] Semantic index  %*
echo       incremental: only new, changed or previously failed books are processed
"%PY%" "%SERVER%" --build-embeddings %*
if errorlevel 1 (
    echo [!] The semantic build stopped with an error ^(see above^). Continuing with the report.
    set "RC=1"
)

echo.
echo [3/4] Figure index ^(captions of EPUB and PDF figures, incremental^)
"%PY%" "%SERVER%" --index-figures
if errorlevel 1 (
    echo [!] The figure index stopped with an error ^(see above^).
    set "RC=1"
)

echo.
echo [4/4] Index report
if not exist "%LOCALAPPDATA%\calibre-mcp" mkdir "%LOCALAPPDATA%\calibre-mcp"
"%PY%" "%SERVER%" --embeddings-report > "%REPORT%" 2>&1
type "%REPORT%"
echo.
echo Report saved to: %REPORT%
echo To retry only the failed books:  update_embeddings.bat --retry-failed
goto :end

:help
echo.
echo  update_embeddings.bat - missing texts (OCR), semantic and figure indexes, report
echo.
echo  USAGE
echo    update_embeddings.bat                      all new/changed books, figures, report
echo    update_embeddings.bat --retry-failed       only the books that failed last time
echo    update_embeddings.bat --books 81,82,89     only these books (forced re-embed)
echo    update_embeddings.bat --max-books 50       at most 50 books this run (resumable)
echo    update_embeddings.bat --rebuild            discard the semantic index and rebuild it
echo    update_embeddings.bat /?                   this help
echo.
echo  Options are passed to "calibre_mcp.py --build-embeddings". Text extraction ^(with OCR
echo  of scanned PDFs when Tesseract is installed^), the figure index and the report always
echo  run. The report is also saved to:
echo    %REPORT%
echo.
goto :end

:end
rem keep the window open when launched by double-click
echo %cmdcmdline% | find /i "/c" >nul && pause
exit /b %RC%
