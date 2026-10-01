# Changelog

**4.3.0 - Copy and save images from the gallery**

- add: image gallery — each image has Copy PNG and Save PNG buttons; JPEG covers are converted to PNG in the browser.
- add: image gallery — when the client denies clipboard access, Copy falls back to a selection copy that Office apps paste as an image.

**4.2.0 - Images shown inline in the chat**

- add: calibre_show_images — shows covers and figures to the user in an inline gallery (MCP Apps) instead of inside the folded tool call.
- add: calibre_show_images — image data goes only to the gallery, so showing images costs no model tokens and the server stays read-only.
- change: calibre_get_cover — covers are decoded with the same size and safety limits as figures.

**4.1.1 - Model downloaded during setup**

- add: `--download-model` — downloads the semantic-search model once into the local cache.
- change: install.ps1 — downloads the semantic-search model during setup, so the first index build or query no longer downloads it.
- change: documentation — new section describing the multilingual embedding model and how it runs locally.

**4.1.0 - Figures and multilingual search**

- add: calibre_list_figures — lists the figures of a book with caption, alt text, chapter or page, and size.
- add: calibre_get_figure — returns one figure from EPUB, PDF, or other formats converted through Calibre.
- add: calibre_render_page — renders a PDF page or an area of it, for diagrams drawn as vectors.
- add: calibre_read_section — Markdown output shows figure ids that can be passed to calibre_get_figure.
- add: calibre_search_semantic — `alt_queries` accepts paraphrases or translations and merges the results.
- change: full-text search — guidance tells the assistant to write queries in the language of the books.

**4.0.5 - Accurate full-text snippets**

- fix: full-text search — snippets now show the passage that matched the query instead of the first occurrence of any query word.
- change: full-text search — snippets respect phrases, NEAR groups, and NOT terms, and list the matched clauses.
- change: full-text search — snippets match whole words unless the query uses a prefix or stemming.

**4.0.4 - Semantic search setup and OpenAI clients**

- change: install.ps1 — installs the semantic-search dependencies by default (skip with `-NoSemantic`); they are skipped on 32-bit Python.
- fix: semantic search — the missing-dependency error now shows the exact install command for the server's own environment.
- fix: semantic search — a failed model download now reports a clear cause (network or proxy) instead of a traceback.
- change: semantic search — the model is stored under `%LOCALAPPDATA%\calibre-mcp\models` instead of the temp folder.
- change: semantic search — building the index uses half the CPU cores by default (`CALIBRE_MCP_EMBED_THREADS`).
- add: documentation — setup instructions for the ChatGPT desktop app, Codex CLI, and the Codex IDE extension.

**4.0.3 - Better duplicates and similar books**

- fix: calibre_find_duplicates — distinct volumes with different subtitles, numbered parts, or series numbers are no longer reported as duplicates.
- add: calibre_find_duplicates — `loose=true` also ignores subtitles and bracketed text.
- fix: calibre_similar_books — books with sparse metadata now get results based on their text content.

**4.0.2 - Custom column reliability**

- fix: custom columns — no longer missing during the first seconds after the machine starts.
- change: release zips — no longer include repository and CI files.

**4.0.1 - Calibre-accurate yes/no columns**

- fix: custom columns — yes/no searches (`yes`, `no`, `true`, `false`, `empty`) now return the same books as Calibre, in both tristate and two-state modes.
- add: custom columns — can be referenced by their visible heading (e.g. `#mustread` for "Must Read").
- change: calibre_get_book — custom column values include the column's visible heading.

**4.0.0 - Calibre-native search and library features**

- add: calibre_search_books — `query` accepts Calibre search syntax: boolean operators, exact and regex matches, numeric and date comparisons, identifiers, and custom columns.
- add: virtual libraries and saved searches — listed with book counts and usable as filters (`virtual_library`, `vl:`, `search:`).
- add: calibre_list_custom_columns — lists custom columns with type, coverage, and top values.
- add: calibre_get_book — includes custom column values, reading progress, and notes on the book's authors, series, and tags.
- add: calibre_reading_progress — shows books being read or finished, from the Calibre viewer.
- add: calibre_get_notes — reads Calibre 7 notes on authors, tags, series, and publishers.
- add: calibre_get_cover — returns the book cover as an image.
- add: calibre_similar_books and calibre_find_duplicates — similar books by metadata or content, and probable duplicates by title, author, or ISBN.
- add: multiple libraries — `CALIBRE_LIBRARIES` configures several libraries, selectable per call with `library`.
- add: calibre_read_section — `output="markdown"` keeps headings, lists, tables, and code blocks.
- add: stemmed full-text search — opt-in with `CALIBRE_MCP_STEMMING=1` (English stemmer).
- add: semantic search — opt-in local embedding index built with `--build-embeddings`, used by calibre_search_semantic.
- add: MCP resources (book card, chapter, highlights) and prompts (summarize, research, compare, highlights, reading status).
- add: calibre_search_books — sorting by series order, rating, and last modified.

**3.2.0 - HTTP transport**

- add: Streamable HTTP transport (`--transport http`) with a mandatory bearer token, Host/Origin checks, and optional TLS.
- add: `--gen-token` — generates a random bearer token for the HTTP transport.
- change: distribution renamed to mcp-calibre; the server file is still `calibre_mcp.py`.

**3.1.1 - Converter detection on Windows**

- fix: Calibre's ebook-convert is now found under both Program Files folders, including with 32-bit Python.
- change: when ebook-convert is not found, the error lists the folders that were searched.

**3.1.0 - Robust text extraction**

- fix: EPUB files with a missing table of contents or broken manifest entries can now be read; problems are reported as warnings.
- add: text extraction — if one format fails, the next available format is tried.
- add: LIT, MOBI, AZW3, RTF, DOC, and ODT books are readable through Calibre's ebook-convert.
- change: PDF books are no longer limited to 400 pages.
- add: text extracted on demand is cached and becomes searchable with full-text search.
- add: scanned PDFs without a text layer return an explicit "OCR needed" error.
- add: `--extract-missing` — extracts and indexes books that Calibre has not indexed yet.
- fix: install.ps1 — a library path ending with a backslash no longer swallows the other parameters.
- add: install.ps1 — warns when the repository or the library is inside OneDrive.
- change: installer messages and documentation are in English; the README is available in English and Italian.

**3.0.0 - First release of this implementation**

- add: read-only access to a Calibre library through SQLite, working while the Calibre GUI is open.
- add: full-text search over the text Calibre has extracted, BM25-ranked and accent-insensitive, with all, any, phrase, and raw modes.
- add: tools to search metadata, read book details, read text by offset, search within a book, read tables of contents, and read EPUB chapters or PDF pages.
- add: tools to browse authors, tags, series, publishers, languages, and formats, and to read Calibre viewer highlights and notes.
- add: incremental background sync of the full-text index.
- add: install.ps1 — Windows installer with library auto-detection and optional Claude Desktop registration.
- add: `--status` and `--sync` command-line options.
