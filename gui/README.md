# gui/: setup wizard and console (developer notes)

Two optional Windows front-ends. How to use them is in the manuals:
[installation](../docs/en/installation.md#option-a-setup-wizard) (wizard) and
[tweaking](../docs/en/tweaking.md#console-graphical-manager) (console); Italian:
[installazione](../docs/it/installation.md), [personalizzazione](../docs/it/tweaking.md). Their interface is in English.

| File | Purpose |
|---|---|
| `setup-wizard.ps1` | WinForms wizard (Windows PowerShell 5.1, ASCII only). Collects choices and runs `install.ps1` unchanged. Started by `../setup-wizard.bat`. |
| `calibre_mcp_console.py` | Desktop console (Python/Tk, standard library only). Started by `../console.bat`. |
| `../tests/test_console_logic.py` | Unit tests of the output classifier and stream reader (run by the CI; skipped where Tk is missing). |
| `../presentation/icon/` | Window and shortcut icon (`favicon.ico`, `mcp-calibre-owl-256.png`). Optional. |

## Design rules

* **The server is never modified or imported.** The console launches `calibre_mcp.py` as a child process with the
  right command line and environment, and reads its stdout and stderr.
* **The wizard offers only what `install.ps1` declares.** Options come from `(Get-Command install.ps1).Parameters`,
  so a switch the installer lacks is disabled instead of passed. Arguments are quoted with the CommandLineToArgvW
  rules (`ConvertTo-QuotedArg`); `setup-wizard.ps1 -SelfTest` checks the quoting round-trips, argument building and
  path resolution without a GUI.
* **Root detection.** Both tools find the repository root as the folder holding `install.ps1` / `calibre_mcp.py`:
  their own folder, or its parent (they live in `gui/`).
* **stdio cannot be supervised.** In stdio mode the child's stdout is the protocol channel and the client owns the
  process, so the console supervises HTTP only; for stdio it offers a protocol self-test and the Claude Desktop log tail.

## Console internals

* **Profiles** (`%LOCALAPPDATA%\calibre-mcp-console\profiles.json`): variables, transport, launcher, window size and split
  position. The variable list is the `SCHEMA` tuple at the top of the file; keep it in step with the environment
  variables of the server (the documentation audit compares them) and the `TASKS` tuple with the server's flags.
* **Classifier** (`Classifier`, `parse_progress`): a stateful, per-stream line classifier (error, warning, status,
  progress, request, debug). It understands Python tracebacks, `\r`-style progress, uvicorn/HTTP access lines and the
  server's level-less log lines; JSON output lines are never read as failures. Covered by `tests/test_console_logic.py`:
  add a case whenever a real output line is misclassified.
* **Token**: stored with Windows DPAPI (`_dpapi`, current user); in memory only where DPAPI is unavailable.
* **Probes**: `mcp_http_probe` and `mcp_stdio_selftest` speak `initialize` + `tools/list` with the standard library.

## Tests

```powershell
python tests\test_console_logic.py
powershell -File gui\setup-wizard.ps1 -SelfTest
```
