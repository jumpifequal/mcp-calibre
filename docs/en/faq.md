# FAQ and troubleshooting

[← README](../../README.md) · [Installation](installation.md) · [Tweaking and under the hood](tweaking.md) · [Skills](skills.md) · **FAQ and troubleshooting** · [Performance](performance.md)

🇬🇧 English · [🇮🇹 Italiano](../it/faq.md)

Find your symptom below. Installation and setup problems come first, then problems while using the server, then the
graphical tools, then the known limits. If nothing matches, see [Still stuck?](#still-stuck).

**Contents**

- [The basics](#the-basics)
- [Installation and setup problems](#installation-and-setup-problems)
- [Problems while using it](#problems-while-using-it)
- [Setup wizard and console problems](#setup-wizard-and-console-problems)
- [Known limitations](#known-limitations)
- [Still stuck?](#still-stuck)

## The basics

### Do I have to start the server myself?

It depends on the connection. With **stdio** (Claude Desktop, the ChatGPT desktop app, Codex) you start nothing: the client launches the server when it needs it and stops it afterwards, so there is no window to keep open, and the console's *Start server* is not needed. Only **Streamable HTTP** (for example Claude Code, or one server shared by several clients) needs a server that you run: `calibre_mcp.py --transport http`, a scheduled task, or *Start server* in the console. The console is optional in every case, and the maintenance jobs (`--sync`, `--build-embeddings`, `--extract-missing`…) never need a running server. See [Connect your AI client](installation.md#connect-your-ai-client).

### Does it change my Calibre library?

No. Calibre's databases are opened in read-only mode (`mode=ro` with `PRAGMA query_only`), book files are only read, and there are no write tools. The server writes only its own cache (the sidecar) and its log. The curation tools (quality report, duplicates, ISBN) report problems; you fix them in Calibre.

### Does Calibre have to be running?

No. Read-only connections never conflict with Calibre's locks, so the server works with Calibre open or closed. One caveat: Calibre extracts the text of your books in the background, at low priority and only while its window is open. To cover the books it has not processed, run `--extract-missing` (see [Calibre prerequisites](installation.md#calibre-prerequisites)).

### Does my data leave my computer?

The server runs on your machine and has no network access at query time (the embedding model is downloaded once during setup; building the semantic index and every semantic query run locally). But what a tool returns goes to your AI client: the snippets, chapters and metadata the assistant asks for reach the AI service you chose, as with any MCP server. Images shown with `calibre_show_images` go to the chat view, not into the model's context.

### Which languages work?

Metadata and full-text search are lexical: the query must be in the language of the books (an Italian query does not match English text), so the assistant is told to translate it, or to combine the translations. Semantic search is multilingual: an Italian question also finds English passages. Stemming is English-only. OCR uses `ita` and `eng` by default; add others with `--download-ocr-langs`.

### Which systems and clients are supported?

Windows 10/11 fully (wizard, installer, console); macOS and Linux with the manual setup. Clients: Claude Desktop, Claude Code, ChatGPT desktop app, Codex CLI and IDE extension, and any MCP client over stdio or HTTP. ChatGPT on the web and claude.ai custom connectors cannot use it. See [Connect your AI client](installation.md#connect-your-ai-client).

### Where does it keep its data?

In `%LOCALAPPDATA%\calibre-mcp\<library-hash>\` for each library (`index.db`, `embeddings.db`, `figures.db`, `converted/`), plus `models/`, `tessdata/` and `calibre-mcp.log` in the folder above. Set `CALIBRE_MCP_DATA` to move it. Deleting it is always safe: everything can be rebuilt from the library. See [Data stores](tweaking.md#architecture).

### What do I do if I add, change or delete a book in Calibre?

Metadata follows Calibre at once; the text indexes catch up by themselves, except the semantic and figure indexes, which you refresh with a command. What happens depends on what you did:

| In Calibre you… | Metadata searches | Full-text search | Semantic search |
|---|---|---|---|
| **add** a book | see it at once | after Calibre has extracted its text (FT indexing, with its window open), or after `--extract-missing`; then at the next sync | run `--build-embeddings` |
| **edit its metadata** (title, authors, tags, custom columns…) | at once (the definitions of custom columns refresh within 30 s) | nothing to do | nothing to do: results show the current title and authors |
| **change its file** (replace or convert a format) | at once | Calibre re-extracts the text and the next sync picks it up | run `--build-embeddings`: the book is reported as `stale` and refreshed |
| **delete** a book | gone at once | removed at the next sync; until then it can still appear as a hit with no title | removed by the next full `--build-embeddings`; until then it can appear with no title, and `--embeddings-report` lists it as `orphan` |

The **sync** of the full-text index runs in the background of the server, at startup and every 10 minutes while it runs (`CALIBRE_MCP_SYNC_INTERVAL`, `0` = at startup only). With stdio the server runs only while your AI client has it open, so restarting the client also forces a sync; or run `--sync` yourself. Books that Calibre has not indexed, scanned PDFs included, are covered by `--extract-missing`. The figure index is refreshed with `--index-figures`, which is incremental.

After a batch of changes the simplest routine is `scripts\update_embeddings.bat`: it runs missing texts with OCR, the semantic build, the figure index and the report, in that order. To see where things stand, ask the assistant for `calibre_library_status` (`texts_extracted`, `calibre_pending`, and the sidecar `pending` and `last_sync`) or run `--embeddings-report` (`missing`, `stale`, `orphan`). More in [Calibre prerequisites](installation.md#calibre-prerequisites) and [Semantic search](tweaking.md#optional-features).

### How much disk, memory and time does it need?

The full-text index is a fraction of the text size and builds in seconds per hundred megabytes; the semantic index is the heavy part (hours of CPU for a first build on a large library). Numbers and tuning are in [Performance](performance.md#sizing-a-real-library).

## Installation and setup problems

The first table collects the setup symptoms already covered by the installer; the questions below add the rest.

| Symptom | Check |
|---|---|
| No `calibre_*` tools in Claude | `mcpServers.calibre` present in the config; Desktop fully restarted; `%APPDATA%\Claude\logs\mcp-server-calibre.log` |
| Server doesn't start | run `python calibre_mcp.py --status` with the same paths as in the config |
| "Semantic search dependencies are missing" | They were installed into a different Python: run the command printed in the error (it uses the server's own `python.exe`), then restart the client |
| Model download failed during setup | Check network/`HTTPS_PROXY`, then `.venv\Scripts\python.exe calibre_mcp.py --download-model`; offline: see [Semantic search model](tweaking.md#semantic-search-model) |
| Codex/ChatGPT: tool times out | Raise `tool_timeout_sec` in `config.toml` (on-demand LIT/MOBI conversion can take minutes) |

### The installer says "Python >= 3.10 required"

Install Python from python.org, not from the Microsoft Store; 3.12 or newer is recommended (SQLite 3.43+ gives a contentless full-text index that uses about a third of the disk space). The installer uses the `py` launcher when present, otherwise `python`.

### "Semantic search skipped: it needs 64-bit Python"

The embedding runtime has no 32-bit builds. Install 64-bit Python and run the installer again, or ignore the warning: the core server works without semantic search.

### My `-Library` path swallowed `-Pdf` and `-Register` ("-Library contains a quote")

A path ending in a backslash inside quotes (`"...\Calibre Library\"`) makes Windows read `\"` as an escaped quote. Remove the trailing backslash. The script detects the problem and stops; the setup wizard removes the backslash for you.

### "metadata.db not found in …"

`-Library` must be the library folder itself, the one that contains `metadata.db`: not its parent and not a subfolder.

### Warning: the repository is inside OneDrive and/or inside the Calibre library

The `.venv` folder holds thousands of files that OneDrive would sync, and Calibre would report an extra folder in its library. Move the repository, for example to `C:\Tools\mcp-calibre`.

### Warning: the library is in a OneDrive folder

Set the library folder to "Always keep on this device"; otherwise reading a book forces a file download. The server works read-only on a OneDrive or network library, but with higher latency and with sync side effects for Calibre itself.

### Tesseract is missing, or winget is not available

The installer runs `winget install --id UB-Mannheim.TesseractOCR -e` (Windows may ask for confirmation). Without winget, install Tesseract from <https://github.com/UB-Mannheim/tesseract/wiki>, then run `calibre_mcp.py --download-ocr-langs ita,eng`. OCR also needs PyMuPDF, so it is skipped with `-Pdf pypdf` or `-Pdf none`. Every optional part is non-blocking: the core server installs anyway.

### The server refuses to start over HTTP

Each refusal names its cause. "Set CALIBRE_MCP_HTTP_TOKEN (generate one with --gen-token), or use --no-auth on a loopback bind": no token configured. "CALIBRE_MCP_HTTP_TOKEN too short (min 24 chars)": generate one with `--gen-token`. "--no-auth is only allowed on a loopback bind": remove `--no-auth` or bind to `127.0.0.1`. "Binding to all interfaces: list the names clients will use with --allowed-host": add `--allowed-host name:port`. See [HTTP transport](installation.md#http-transport).

### An HTTP client gets 401 or 403

401 means a missing or wrong bearer token (the server logs `HTTP 401 from <address> <path>`). A request with a browser Origin that is not allowed gets 403 (`--allowed-origin`), and a Host header that is not in the allow-list is refused (`--allowed-host`).

### The embedding model download failed, or the dependencies seem missing

See the first table above for the exact messages. Offline, copy the model folder from another machine into the cache directory, or use `CALIBRE_MCP_EMBED_BACKEND=hash` (a lexical fallback, not semantic): see [Semantic search model](tweaking.md#semantic-search-model).

## Problems while using it

| Symptom | Check |
|---|---|
| Full-text search finds little | `calibre_library_status`: low `texts_extracted` → leave Calibre open or run `--extract-missing` |
| LIT/MOBI books fail | `ebook_convert` is `null` in status → set `CALIBRE_EBOOK_CONVERT` |
| "OCR needed" / scanned PDF without text | `install.ps1` (or `--download-ocr-langs ita,eng` after installing Tesseract), then `--extract-missing`; a PDF with a garbled text layer: `--extract-missing --books <id> --force-ocr` |
| `--build-embeddings` reported failed books | `--embeddings-report` shows them with the error; fix, then `--build-embeddings --retry-failed` |
| "The semantic index was built by an older version" | index from 4.x: run `.venv\Scripts\python.exe calibre_mcp.py --build-embeddings` once |
| Semantic results all `low_confidence` | the topic may not be in the library, or the relevant books are not indexed yet: check `semantic_index.books` in `calibre_library_status` |
| "Figure index not built" / figure search finds nothing | run `calibre_mcp.py --index-figures`; only EPUB and PDF figures with a caption or alt text are indexed |
| Chapter map has one chapter or odd titles | the book has no TOC and no recognisable headings; use `calibre_read_text` by offset, or `calibre_get_toc` for EPUB sections |
| Legal gate FAIL | the report names the check and, for `longest_run`, the copied text: rewrite it, then re-run |

### A search for an Italian word finds nothing in my English books

Full-text search is lexical, so the query must use the language of the books. Ask the assistant to translate the query, or to combine the translations (`mode="any"`). For meaning-based search use `calibre_search_semantic`, which is multilingual.

### Images do not appear in the chat

`calibre_show_images` uses the MCP Apps extension, supported by Claude (web and desktop) and ChatGPT, among others. A client without it shows only the text summary, which tells the model to retry with `also_for_model=true` (small thumbnails for the model, inside the tool block). Rendering issues have been reported on some Claude Desktop for Windows builds; the fallback covers them too. See [Showing images in the chat](tweaking.md#showing-images-in-the-chat).

### The first semantic query after starting is slower

The first semantic query loads the vectors into memory: in the benchmark it took about 291 ms against about 75 ms for the following ones. Right after a first install the background sync may still be building the full-text index (about 21 s for 524 MB of text in the benchmark; it pauses 5 ms per document by default, `CALIBRE_MCP_THROTTLE_MS`), so searches work but only cover what is indexed so far: `calibre_library_status` shows the state. Typical timings are in [Performance](performance.md#results).

## Setup wizard and console problems

### The wizard says "Blocking problem found"

Only three things block the wizard: `install.ps1` or `calibre_mcp.py` missing from the install folder, or Python not found or older than 3.10. Fix it and press *Re-check*. Everything else (OneDrive, Tesseract, `ebook-convert`) is a warning.

### An option in the wizard is greyed out

The options come from the parameters `install.ps1` declares. If your copy of the installer does not have a switch (for example `-NoOcr`), the wizard disables that option instead of passing an unknown parameter.

### The console says "calibre_mcp.py not found"

It looks in the folder set as *Server folder* in Settings, then in its own folder, then in the parent of the `gui/` folder. Set *Server folder* to the repository root.

### The Start button is disabled and the state says STDIO

This is normal: in stdio mode the AI client starts and owns the server (you need to start nothing) and the pipe carries the protocol, so the console cannot supervise it. Switch the Transport tab to HTTP only if you run an HTTP server. For stdio, use *Self-test* and *Follow Claude Desktop's MCP log* instead. See [Console](tweaking.md#console-graphical-manager).

### The console refuses to start the server

The Transport tab names the reason. It blocks a missing or short token (under 24 characters; press *Generate*), `--no-auth` off loopback, a non-loopback bind without an allowed host, and TLS with a certificate but no key. A non-loopback bind without TLS is allowed with a warning.

### My variables set with `set` are ignored by the console

By default the console removes the variables it manages from the inherited environment, so the profile is the single source of truth. Use *Import from environment* (start the console from the shell where you ran `set`), or untick *Isolate from the system environment*.

### Where does the console keep its settings and the token?

In `%LOCALAPPDATA%\calibre-mcp-console\profiles.json`. The token is protected with Windows DPAPI for the current Windows user: a profile copied to another account or computer cannot decrypt it, so generate a new token there.

## Known limitations

- Composite (template-computed) custom columns are not readable: Calibre does not store their values.
- The search syntax is a large subset of Calibre's: no `template:`, `marked:`, `ondevice:`, and hierarchical tag matching (`tag:.parent`) is not special-cased.
- Stemming is English-only (Porter).
- Chapter detection without a TOC is heuristic (keywords, numbering, short all-caps lines); unusual layouts may give a coarse map.
- Figure search covers EPUB and PDF; figures inside LIT/MOBI/AZW3 are reachable per book with `calibre_list_figures`, not through the library-wide index.
- OCR quality depends on the scan: handwriting, multi-column layouts and tables come out imperfect with Tesseract.
- Library on a network share or OneDrive: works read-only, but with higher latency and with sync side effects for Calibre itself.
- Offsets returned by `search_fulltext` refer to the text of the reported `format`, not to the EPUB sections extracted on demand.

## Still stuck?

Collect this before asking for help; it answers most questions:

1. `.venv\Scripts\python.exe calibre_mcp.py --status`: library, versions, backends, text coverage.
2. In your AI client, ask for `calibre_library_status`: sidecar, stemmed and semantic indexes, enabled features.
3. The logs: `%LOCALAPPDATA%\calibre-mcp\calibre-mcp.log` (the server) and, for Claude Desktop,
   `%APPDATA%\Claude\logs\mcp-server-calibre.log`. Set `CALIBRE_MCP_LOG_LEVEL=DEBUG` for more detail; note that
   DEBUG also logs your queries, so review the log before sharing it. The console's *Save* button writes its log to a file.
4. Your Windows and Python versions, and the `server_version` shown by `--status`.

Then open an issue at <https://github.com/jumpifequal/mcp-calibre/issues> with the steps that led to the problem
and what you collected.
