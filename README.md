# mcp-calibre

🇬🇧 English · [🇮🇹 Italiano](README.it.md)

A read-only MCP server that gives Claude (and any MCP client) native access to a local Calibre library:
metadata, full-text search across EPUB/PDF/MOBI/LIT/…, chapter and page reading, highlights and notes.
Transports: **stdio** (Claude Desktop) and **Streamable HTTP** (Claude Code, other clients, remote use).

## Design

| Aspect | Choice |
|---|---|
| Data access | direct SQLite on `metadata.db` / `full-text-search.db` in `mode=ro`: no `calibredb` subprocesses, millisecond queries |
| Calibre GUI open | supported: read-only connections never conflict with Calibre's locks |
| Full-text | sidecar FTS5 index over the text **Calibre has already extracted** (EPUB/PDF/MOBI/DOCX…) |
| Readable formats | Calibre FTS text, then on-demand extraction: EPUB (built-in), PDF (PyMuPDF/pypdf), everything else via `ebook-convert` |
| Transports | stdio and Streamable HTTP (stateless, JSON responses, bearer auth, DNS-rebinding protection, optional TLS) |
| Portability | Windows/macOS/Linux, library auto-detection |
| Logging | stderr + `%LOCALAPPDATA%\calibre-mcp\calibre-mcp.log`, queries logged only at DEBUG |

## Why a sidecar index

Calibre's FTS5 table uses a custom tokenizer (`calibre`) implemented in Calibre's C extension, so stock SQLite
cannot run `MATCH` against it. The plain-text `books_text` table, however, is readable. The server therefore:

1. reads `books_text` read-only;
2. maintains an FTS5 index (`unicode61 remove_diacritics 2`) in `%LOCALAPPDATA%\calibre-mcp\<library-hash>\index.db`;
3. syncs it **incrementally** by `text_hash` (background thread at startup, then every 10 minutes).

With SQLite ≥ 3.43 (Python 3.12+ from python.org) the index is *contentless* (`contentless_delete=1`) and does
not duplicate the text. With older SQLite it falls back to standard FTS5 (roughly the size of the text).

Measured on a synthetic dataset (1,500 books, ~525 MB of text, single container core):

| Operation | Time |
|---|---|
| Initial index build (one-off) | ~30 s, 193 MB index |
| Incremental sync (1 change, 1 removal) | 0.14 s |
| Full-text search, 10 books × 3 snippets | 80–90 ms |
| Full-text search without snippets, 50 books | ~3 ms |
| Metadata search | ~5 ms |
| `read_text` / `find_in_book` | 1–10 ms |

## Text extraction chain

For each book, in order:

1. Calibre's FTS text (already extracted by Calibre, fastest);
2. local cache;
3. on-demand extraction:
   - EPUB: built-in parser, tolerant of broken container/OPF/spine/TOC (problems become `warnings`);
   - PDF: PyMuPDF or pypdf, no page limit;
   - TXT: read directly;
   - anything else (LIT, MOBI, AZW3, RTF, DOC, ODT…): Calibre's `ebook-convert`.

If one format fails, the next one is tried. Extracted text is cached **and indexed**, so a book read once also
becomes findable through `calibre_search_fulltext`. Scanned PDFs without a text layer return an explicit
"OCR needed" error.

## Calibre prerequisites

Enable full-text indexing in Calibre (the **FT** button next to the search bar). Calibre extracts text in the
background, at low priority and **only while the GUI is running**. `calibre_library_status` shows the coverage
(`texts_extracted`, `calibre_pending`, `extraction_errors`).

To close the gap without leaving Calibre open, run the batch extractor (low priority, resumable):

```powershell
.\.venv\Scripts\python.exe .\calibre_mcp.py --extract-missing --max-books 50
```

## Installation (Windows)

```powershell
git clone https://github.com/jumpifequal/mcp-calibre C:\Tools\mcp-calibre
```

Clone or unzip the repo **outside** the Calibre library and outside OneDrive (e.g. `C:\Tools\mcp-calibre`), then:

```powershell
cd C:\Tools\mcp-calibre
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Library "D:\Books\Calibre Library" -Pdf pymupdf -Register
```

> **Do not end the `-Library` path with a backslash inside quotes** (`"...\Calibre Library\"`): Windows reads `\"`
> as an escaped quote and the following parameters get swallowed. The script detects this and stops.

`-Register` edits `%APPDATA%\Claude\claude_desktop_config.json` (with a backup, UTF-8 without BOM). Without
`-Register` the script prints the JSON snippet to paste. Manual configuration:

```json
{
  "mcpServers": {
    "calibre": {
      "command": "C:\\Tools\\mcp-calibre\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Tools\\mcp-calibre\\calibre_mcp.py"],
      "env": { "CALIBRE_LIBRARY": "D:\\Books\\Calibre Library" }
    }
  }
}
```

Then fully restart Claude Desktop (quit from the tray icon, not just close the window).

CLI: `python calibre_mcp.py --status` · `--sync` · `--extract-missing [--max-books N]` · `--library <path>` ·
`--transport http` (see below) · `--gen-token`.

## HTTP transport

Streamable HTTP endpoint (stateless, JSON responses), for Claude Code, other MCP clients or a server shared on
the LAN. Bearer auth is **mandatory** unless you explicitly pass `--no-auth`, which is only accepted on loopback.

```powershell
# one-off: generate a token and store it for your user
$t = .\.venv\Scripts\python.exe .\calibre_mcp.py --gen-token
[Environment]::SetEnvironmentVariable('CALIBRE_MCP_HTTP_TOKEN', $t, 'User')
$env:CALIBRE_MCP_HTTP_TOKEN = $t

# run (default bind 127.0.0.1:8765, endpoint /mcp)
.\.venv\Scripts\python.exe .\calibre_mcp.py --transport http
```

Clients:

```powershell
# Claude Code
claude mcp add --transport http calibre http://127.0.0.1:8765/mcp --header "Authorization: Bearer $env:CALIBRE_MCP_HTTP_TOKEN"
```

For Claude Desktop stdio remains the simplest option. If you want Desktop to use the HTTP server (e.g. one shared
instance), bridge it with `mcp-remote` (requires Node.js):

```json
{
  "mcpServers": {
    "calibre-http": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:8765/mcp", "--header", "Authorization:${AUTH}"],
      "env": { "AUTH": "Bearer <token>" }
    }
  }
}
```

The `Authorization:${AUTH}` form avoids a known issue with spaces inside `args` on Windows.

Run at logon in the background (no console window):

```powershell
$repo = 'C:\Tools\mcp-calibre'
$act  = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" -Argument "`"$repo\calibre_mcp.py`" --transport http" -WorkingDirectory $repo
Register-ScheduledTask -TaskName 'calibre-mcp' -Action $act -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0)
```

LAN exposure (not recommended without TLS):

```powershell
.\.venv\Scripts\python.exe .\calibre_mcp.py --transport http --host 0.0.0.0 --allowed-host mybox.lan:8765 `
    --ssl-certfile .\cert.pem --ssl-keyfile .\key.pem
```

| Option | Default | Notes |
|---|---|---|
| `--host` | `127.0.0.1` | non-loopback without TLS logs a warning |
| `--port` | `8765` | |
| `--path` | `/mcp` | |
| `--allowed-host` | loopback names | Host header allow-list (DNS-rebinding protection); `name:*` = any port. Required with `0.0.0.0` |
| `--allowed-origin` | none | browser Origins allowed; requests with any other Origin get 403 |
| `--ssl-certfile` / `--ssl-keyfile` | — | native TLS (or put a reverse proxy in front) |
| `--no-auth` | off | loopback only |

claude.ai custom connectors call the server from Anthropic's cloud, so they need a public HTTPS endpoint and
OAuth, not a static token: this server is not designed for that exposure.

## Tools

| Tool | Purpose |
|---|---|
| `calibre_search_books` | Metadata search: free text, title/author/tag/series/publisher/language/format/identifier, rating, dates, `has_annotations`, sorting, pagination |
| `calibre_search_fulltext` | Content search, BM25-ranked, accent-insensitive. Modes `all`/`any`/`phrase`/`raw` (FTS5: `NEAR`, `OR`, `prefix*`). Metadata filters narrow the candidate books; snippets carry an `offset` |
| `calibre_get_book` | Full metadata, identifiers, description, formats, text available per format, Calibre extraction errors |
| `calibre_read_text` | Text window by offset (optionally centred on a snippet offset) |
| `calibre_find_in_book` | Keyword-in-context search inside one book, paginated |
| `calibre_get_toc` | EPUB TOC (nav/NCX → section indices) or PDF outline + page count |
| `calibre_read_section` | One EPUB chapter or a PDF page range (max 30 per call), for precise citations |
| `calibre_list_facets` | Authors/tags/series/publishers/languages/formats with book counts |
| `calibre_get_annotations` | Highlights, notes and bookmarks from the Calibre viewer (one book or the whole library) |
| `calibre_library_status` | Diagnostics: Calibre FTS coverage, sidecar state, PDF backend, `ebook-convert` path, SQLite version |

## Environment variables

| Variable | Default |
|---|---|
| `CALIBRE_LIBRARY` | auto-detected from `%APPDATA%\calibre\global.py.json`, then `~\Calibre Library` |
| `CALIBRE_MCP_DATA` | `%LOCALAPPDATA%\calibre-mcp` |
| `CALIBRE_MCP_MAX_CHARS` | `12000` (cap per read call: controls token usage) |
| `CALIBRE_MCP_SYNC_INTERVAL` | `600` s (`0` = startup only) |
| `CALIBRE_MCP_THROTTLE_MS` | `5` ms pause per indexed document |
| `CALIBRE_EBOOK_CONVERT` | auto-detected: PATH, then `Calibre2\ebook-convert.exe` under both `Program Files` and `Program Files (x86)` (also from 32-bit processes, via `%ProgramW6432%`) |
| `CALIBRE_MCP_CONVERT_TIMEOUT` | `180` s per conversion |
| `CALIBRE_MCP_LOG_LEVEL` | `INFO` (`DEBUG` also logs queries) |
| `CALIBRE_MCP_HTTP_TOKEN` | — (required for `--transport http`, min 24 chars) |

## Troubleshooting

| Symptom | Check |
|---|---|
| No `calibre_*` tools in Claude | `mcpServers.calibre` present in the config; Desktop fully restarted; `%APPDATA%\Claude\logs\mcp-server-calibre.log` |
| Server doesn't start | run `python calibre_mcp.py --status` with the same paths as in the config |
| Full-text search finds little | `calibre_library_status`: low `texts_extracted` → leave Calibre open or run `--extract-missing` |
| LIT/MOBI books fail | `ebook_convert` is `null` in status → set `CALIBRE_EBOOK_CONVERT` |
| "OCR needed" | scanned PDF without a text layer: run OCR (e.g. OCRmyPDF) and re-add it to Calibre |

## Security notes

- **HTTP**: loopback bind by default; static bearer token compared in constant time (min 24 chars, `--gen-token` = 256 bits); Host/Origin validation against DNS rebinding; no `Server` header; `--no-auth` refused off loopback. The token grants read access to the whole library: treat it like a password. Without TLS, token and book content travel in clear on the network.
- **Read-only by design**: SQLite connections in `mode=ro` with `PRAGMA query_only`; no write tools, no shell. The only subprocess is `ebook-convert` (list argv, no shell, timeout, captured stdout, below-normal priority, temporary output directory).
- **Path confinement**: paths derived from the DB are resolved and rejected if they leave the library root.
- **FTS queries**: in `all`/`any`/`phrase` every token is quoted, so FTS5 operators in user input cannot change query semantics; `raw` is opt-in and syntax errors are handled.
- **Untrusted content parsing**: EPUBs have per-member and total size limits (anti zip-bomb) and in-archive path confinement; XML goes through `defusedxml`; PDFs are parsed only on demand. PyMuPDF and Calibre's converters are native code (memory-safety attack surface): if that risk is not acceptable, use `-Pdf pypdf` or `none`, leave `ebook-convert` unavailable, and rely on Calibre's own indexing.
- **Indirect prompt injection**: book text and annotations are third-party content returned to the model. The server's `instructions` declare this explicitly, but that is not a strong control: avoid combining this server, in the same session, with high-impact tools (email sending, shell, browser).
- **Licences**: PyMuPDF is AGPL-3.0; pypdf is BSD.

## Known limitations

- Calibre custom columns (`custom_column_N` tables) are not exposed.
- One library per server instance (for several libraries: several `mcpServers` entries with different `CALIBRE_LIBRARY` values).
- Library on a network share or OneDrive: works read-only, but with higher latency and with sync side effects for Calibre itself.
- Offsets returned by `search_fulltext` refer to the text of the reported `format`, not to the EPUB sections extracted on demand.

## Background

The idea of exposing a Calibre library through MCP was first explored by the bash-based
[trieloff/calibre-mcp](https://github.com/trieloff/calibre-mcp). This project is an independent implementation
and shares no code with it.

## Licence

Apache-2.0.
