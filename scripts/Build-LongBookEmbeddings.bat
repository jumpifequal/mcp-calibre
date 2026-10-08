@echo off
REM ===========================================================================
REM Build-LongBookEmbeddings.bat
REM
REM Builds embeddings for very long books by raising the per-book chunk cap.
REM
REM Thin wrapper around "calibre_mcp.py --build-embeddings". The server caps
REM the number of chunks per book (CALIBRE_MCP_EMBED_MAX_CHUNKS); very long
REM volumes exceed it and get truncated, leaving the tail of the book
REM unindexed. This script raises the cap, optionally limits ONNX threads,
REM runs the build (in one call or in batches) and writes a JSON report.
REM
REM Run "Build-LongBookEmbeddings.bat --help" for usage.
REM ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion

REM --- Defaults --------------------------------------------------------------
set "MAX_CHUNKS=8000"
set "THREADS=0"
set "BATCH_SIZE=0"
set "PERSIST=0"
set "PY=.venv\Scripts\python.exe"
set "ENTRY=calibre_mcp.py"
set "REPORT=embeddings-report.json"
set "SKIP_REPORT=0"
set "BOOKS_ARG="
set "BOOKS_FILE="
set "IDS="
set "COUNT=0"
set "BAD="

REM --- Parse arguments -------------------------------------------------------
:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="/?"          goto :usage
if /i "%~1"=="-h"          goto :usage
if /i "%~1"=="--help"      goto :usage

if /i "%~1"=="--persist" (
  set "PERSIST=1"
  shift
  goto :parse
)
if /i "%~1"=="--skip-report" (
  set "SKIP_REPORT=1"
  shift
  goto :parse
)
if /i "%~1"=="--books" (
  if "%~2"=="" goto :err_value
  set "BOOKS_ARG=!BOOKS_ARG! %~2"
  shift
  shift
  goto :parse
)
if /i "%~1"=="--books-file" (
  if "%~2"=="" goto :err_value
  set "BOOKS_FILE=%~2"
  shift
  shift
  goto :parse
)
if /i "%~1"=="--max-chunks" (
  if "%~2"=="" goto :err_value
  set "MAX_CHUNKS=%~2"
  shift
  shift
  goto :parse
)
if /i "%~1"=="--threads" (
  if "%~2"=="" goto :err_value
  set "THREADS=%~2"
  shift
  shift
  goto :parse
)
if /i "%~1"=="--batch-size" (
  if "%~2"=="" goto :err_value
  set "BATCH_SIZE=%~2"
  shift
  shift
  goto :parse
)
if /i "%~1"=="--python" (
  if "%~2"=="" goto :err_value
  set "PY=%~2"
  shift
  shift
  goto :parse
)
if /i "%~1"=="--entrypoint" (
  if "%~2"=="" goto :err_value
  set "ENTRY=%~2"
  shift
  shift
  goto :parse
)
if /i "%~1"=="--report" (
  if "%~2"=="" goto :err_value
  set "REPORT=%~2"
  shift
  shift
  goto :parse
)

echo ERROR: unknown argument: %~1
echo Run with --help for usage.
exit /b 1

:err_value
echo ERROR: option %~1 requires a value.
echo Run with --help for usage.
exit /b 1

:parsed

REM --- Validate numeric options ----------------------------------------------
call :check_int MAX_CHUNKS --max-chunks 1 1000000
if errorlevel 1 exit /b 1
call :check_int THREADS --threads 0 256
if errorlevel 1 exit /b 1
call :check_int BATCH_SIZE --batch-size 0 100000
if errorlevel 1 exit /b 1

REM --- Collect book IDs ------------------------------------------------------
REM IDs may come from --books, from --books-file, or both. Duplicates are
REM dropped; first-seen order is preserved.
if defined BOOKS_ARG call :add_tokens "!BOOKS_ARG!"

if defined BOOKS_FILE (
  if not exist "!BOOKS_FILE!" (
    echo ERROR: ID file not found: !BOOKS_FILE!
    exit /b 1
  )
  REM eol=# skips lines that start with '#'; the inner loop strips trailing
  REM comments ('#' to end of line).
  for /f "usebackq eol=# delims=" %%L in ("!BOOKS_FILE!") do (
    for /f "tokens=1 delims=#" %%C in ("%%L") do call :add_tokens "%%C"
  )
)

if defined BAD exit /b 1
if %COUNT% EQU 0 (
  echo ERROR: no book IDs provided. Use --books and/or --books-file.
  echo Run with --help for usage.
  exit /b 1
)

REM --- Preflight checks ------------------------------------------------------
REM Fail early with a clear message instead of a cryptic Python/launcher error.
if not exist "!PY!" (
  where "!PY!" >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Python interpreter not found: !PY!
    exit /b 1
  )
)
if not exist "!ENTRY!" (
  echo ERROR: entrypoint not found: !ENTRY!
  echo Run from the project root or pass --entrypoint.
  exit /b 1
)

REM --- Environment configuration ---------------------------------------------
REM Session scope: inherited by the Python child process only. The setlocal
REM above guarantees nothing leaks into the calling shell.
set "CALIBRE_MCP_EMBED_MAX_CHUNKS=%MAX_CHUNKS%"

REM User scope (optional): inherited by future shells / server launches.
REM Note: setx does not affect shells that are already open.
if "%PERSIST%"=="1" setx CALIBRE_MCP_EMBED_MAX_CHUNKS "%MAX_CHUNKS%" >nul

REM ONNX thread limit (optional). Unset => server default (half the cores).
set "THREADS_LABEL=default"
if %THREADS% GTR 0 (
  set "CALIBRE_MCP_EMBED_THREADS=%THREADS%"
  set "THREADS_LABEL=%THREADS%"
)

REM --- Batch sizing ----------------------------------------------------------
REM BATCH_SIZE 0 means a single build call for all IDs.
if %BATCH_SIZE% EQU 0 set "BATCH_SIZE=%COUNT%"
set /a BATCH_COUNT=(COUNT + BATCH_SIZE - 1) / BATCH_SIZE

echo Books: %COUNT% ^| MaxChunks: %MAX_CHUNKS% ^| Threads: %THREADS_LABEL% ^| Batches: %BATCH_COUNT%

REM --- Build embeddings ------------------------------------------------------
call :now START_S

set "BATCH="
set "IN_BATCH=0"
set "BATCH_NO=0"
for %%I in (!IDS!) do (
  if defined BATCH (
    set "BATCH=!BATCH!,%%I"
  ) else (
    set "BATCH=%%I"
  )
  set /a IN_BATCH+=1
  if !IN_BATCH! EQU %BATCH_SIZE% (
    call :run_batch
    if errorlevel 1 exit /b !RC!
  )
)
REM Flush the last, possibly partial, batch.
if !IN_BATCH! GTR 0 (
  call :run_batch
  if errorlevel 1 exit /b !RC!
)

call :now END_S
set /a ELAPSED=END_S-START_S
REM Handle a run that crosses midnight.
if !ELAPSED! LSS 0 set /a ELAPSED+=86400
set /a EH=ELAPSED/3600, EM=(ELAPSED %% 3600)/60, ES=ELAPSED %% 60
set "EH=0!EH!"
set "EM=0!EM!"
set "ES=0!ES!"
echo Elapsed: !EH:~-2!:!EM:~-2!:!ES:~-2!

REM --- Embeddings report -----------------------------------------------------
if "%SKIP_REPORT%"=="1" exit /b 0

REM Force UTF-8 on Python's stdout for this call only, so the redirected JSON
REM is UTF-8 regardless of the console code page.
set "PYTHONUTF8=1"
"!PY!" "!ENTRY!" --embeddings-report --json > "!REPORT!"
set "RC=!ERRORLEVEL!"
set "PYTHONUTF8="
if not "!RC!"=="0" (
  echo ERROR: report generation failed ^(exit code !RC!^).
  if exist "!REPORT!" del "!REPORT!"
  exit /b !RC!
)
for %%F in ("!REPORT!") do echo Report: %%~fF
exit /b 0


REM ===========================================================================
REM Subroutines
REM ===========================================================================

REM :run_batch - runs one build call for the IDs currently in BATCH, then
REM resets the batch. Sets RC and returns it as the exit code.
:run_batch
set /a BATCH_NO+=1
echo [!BATCH_NO!/%BATCH_COUNT%] !IN_BATCH! books: !BATCH!
REM The ID list is quoted so cmd does not treat commas as delimiters.
"!PY!" "!ENTRY!" --build-embeddings --books "!BATCH!"
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
  echo ERROR: build failed on batch !BATCH_NO!/%BATCH_COUNT% ^(exit code !RC!^).
  echo Batch IDs: !BATCH!
  exit /b !RC!
)
set "BATCH="
set "IN_BATCH=0"
exit /b 0

REM :add_tokens "list" - splits a list of IDs separated by commas, semicolons
REM or spaces; validates each as a non-negative integer and appends the new
REM ones to IDS. Sets BAD=1 on invalid input.
:add_tokens
set "RAW=%~1"
set "RAW=!RAW:,= !"
set "RAW=!RAW:;= !"
for %%T in (!RAW!) do (
  call :is_num "%%T"
  if errorlevel 1 (
    echo ERROR: invalid book ID: %%T
    set "BAD=1"
  ) else (
    echo( !IDS! |findstr /c:" %%T " >nul
    if errorlevel 1 (
      set "IDS=!IDS! %%T"
      set /a COUNT+=1
    )
  )
)
exit /b 0

REM :is_num "value" - errorlevel 0 if value is a non-negative integer.
:is_num
echo(%~1|findstr /r /x "[0-9][0-9]*" >nul
exit /b

REM :check_int VARNAME OPTION MIN MAX - validates an integer option range.
:check_int
call :is_num "!%~1!"
if errorlevel 1 goto :check_int_bad
if !%~1! LSS %~3 goto :check_int_bad
if !%~1! GTR %~4 goto :check_int_bad
exit /b 0
:check_int_bad
echo ERROR: %~2 must be an integer between %~3 and %~4.
exit /b 1

REM :now VARNAME - stores the current time of day, in seconds, in VARNAME.
REM The "1" prefix and -100 avoid octal parsing of values like 08 and 09.
:now
for /f "tokens=1-3 delims=:., " %%a in ("%TIME: =0%") do (
  set /a "%~1=(1%%a-100)*3600+(1%%b-100)*60+(1%%c-100)"
)
exit /b 0


REM ===========================================================================
REM Help
REM ===========================================================================
:usage
echo.
echo Build-LongBookEmbeddings.bat - build embeddings for very long books
echo.
echo USAGE
echo   Build-LongBookEmbeddings.bat [options]
echo.
echo   At least one of --books or --books-file is required.
echo.
echo OPTIONS
echo   --books IDS         Book IDs separated by commas, e.g. 32,33,1047
echo                       May be repeated; combined with --books-file.
echo   --books-file FILE   Text file with IDs separated by commas, spaces,
echo                       semicolons or newlines. Everything after '#' on a
echo                       line is a comment, so IDs can be grouped by topic.
echo   --max-chunks N      Max chunks per book (CALIBRE_MCP_EMBED_MAX_CHUNKS).
echo                       Default 8000, range 1-1000000. Higher values index
echo                       longer books fully, at the cost of build time,
echo                       memory and index size.
echo   --threads N         ONNX threads (CALIBRE_MCP_EMBED_THREADS).
echo                       Default 0 = unset, server uses half the CPU cores.
echo                       Lower it to keep the machine responsive.
echo   --batch-size N      Split IDs into batches of N books, one build call
echo                       each. A failure reports the exact batch, so you can
echo                       resume with the remaining IDs. Default 0 = one call.
echo   --persist           Also store --max-chunks as a persistent user-level
echo                       variable via setx. Open shells are not affected.
echo                       Without it the value applies to this run only.
echo   --python PATH       Python interpreter.
echo                       Default: .venv\Scripts\python.exe
echo   --entrypoint PATH   MCP server script. Default: calibre_mcp.py
echo   --report PATH       JSON embeddings report. Default:
echo                       embeddings-report.json (UTF-8)
echo   --skip-report       Do not generate the final report.
echo   -h, --help, /?      Show this help.
echo.
echo EXAMPLES
echo   Build-LongBookEmbeddings.bat --books 32,33,1047
echo   Build-LongBookEmbeddings.bat --books 32,33,1047 --max-chunks 12000
echo   Build-LongBookEmbeddings.bat --books-file books.txt --batch-size 20 --threads 4 --persist
echo.
echo NOTES
echo   - Run from the project root, where .venv and calibre_mcp.py live, or
echo     pass --python and --entrypoint explicitly.
echo   - Duplicate IDs are removed; first-seen order is preserved.
echo   - Stops at the first failing step and returns that exit code.
echo     Argument and validation errors return 1.
echo.
exit /b 0
