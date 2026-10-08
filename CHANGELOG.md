# Changelog

**5.3.2 - Fixing su embeddings**

* fix: increased embeddings cap to 8000 (variable CALIBRE_MCP_EMBED_MAX_CHUNKS), so longer books are correctly managed via internal language model

* add: .sh and .ps1 scripts to explicitly create embeddings for long books (find it under scripts)

* fix: changed CALIBRE_MCP_STEMMING to 1 by default (this way you can search for *exploit* and find also *exploitation*). Stemming works only in English

**5.3.1 - Screenshots in the READMEs**

- add: README — screenshots of the setup wizard and the console (`presentation/screenshots/`). The console images are real captures; the wizard images are illustrations drawn from its layout.

**5.3.0 - Setup wizard, console and repository layout**

- add: `setup-wizard.bat` — graphical setup that collects the choices and runs `install.ps1`; it offers only the options the installer declares and quotes paths safely, so a library path ending in a backslash no longer breaks the command line.
- add: `console.bat` — desktop console that launches the server over HTTP and runs the maintenance jobs, with settings profiles in place of `set` lines, output classified into errors, warnings, progress and requests, and a protocol self-test (HTTP and stdio).
- add: console — writes the Claude Desktop entry (with a backup), copies the Claude Code command and the `mcp-remote` JSON, and follows Claude Desktop's own MCP log.
- add: project icon — a puffy owl librarian (SVG, PNG sizes, favicon, 1280×640 GitHub social preview) in `presentation/icon/`, shown at the top of the READMEs and used as the window and shortcut icon of the console and the setup wizard.
- add: documentation in four manuals, in English and Italian (`docs/en`, `docs/it`): installation (wizard, script, manual), tweaking and internals, FAQ and troubleshooting, performance. The READMEs are now short presentation pages that link to them.
- add: `tests/bench_synthetic.py` — reproducible performance benchmark on a synthetic library (default 1,500 books, ~525 MB of text); the figures in the README and in the performance manual come from its reference run (`tests/bench_reference.json`).
- change: README performance figures replaced by the benchmark's measurements (index build 21 s, 148 MB index, full-text with snippets 25–63 ms on one 2.1 GHz core).
- change: README — the companion skills are highlighted among the reasons to use the project, with two new examples (a book's method turned into a skill; two books run as two agents that debate or collaborate); the manual explains how to set both up.
- add: FAQ — with stdio nothing needs to be started (the client launches the server); *Start server* in the console is only for an HTTP server.
- add: skill `calibre-book-agent` — give it a book number or title and it writes an agent (a Claude Code subagent file or a system prompt) grounded in the book: principles, decision heuristics, vocabulary, blind spots, a protocol that checks the book and cites the chapter before claiming what it says, and rules for debating or collaborating with another book-agent. Verified with the legal gate and a three-question smoke test.
- add: skill `calibre-book-redteam` — give it a book number or title and it extracts the central claims, checks the book's internal consistency and searches the rest of the library for support and contradiction, then delivers a claim-by-claim report (steelman, counter-sources, rating) that passes the legal gate. Library evidence only.
- add: `tests/test_skills.py` — checks every skill against the server (every tool, keyword argument and flag a skill names must exist) and runs the prescribed call sequences on the fake library; it is part of the CI.
- change: architecture figure updated (`presentation/Architecture_and_Technical_Overview.png`): it now shows the 30 tools, 4 resources, 5 prompts and the image gallery, the semantic hybrid search sequence, the sidecar cache, the extraction chain, the legal gate and the safety model. Lettering errors of the generated image corrected (PRAGMA, FTS5, int8, BM25, Auth, `calibre-mcp\<library-hash>`, untrusted, OCR) and the corner watermark removed.
- add: skills manual (`docs/en/skills.md`, `docs/it/skills.md`) — what each of the four skills does, how to install and ask for it, what it produces, its limits, how to run two books against each other, the legal gate, and a skills FAQ. The skills material moved out of the tweaking manual.
- change: README — new section "Books that work for you" ("I libri che lavorano per te"): what the four skills do, in terms of results, with a link to the skills manual.
- add: FAQ — what to do when you add, change or delete a book in Calibre: what updates by itself, what needs `--extract-missing`, `--sync`, `--build-embeddings` or `--index-figures`, and what a deleted book looks like until the indexes catch up.
- change: README — M8ven MCP Trust Index badge (independent static scan; the score updates by itself; new projects are capped at grade C).
- change: repository layout — the architecture figure and the two slide decks are under `presentation/` (the duplicate `Documentation/` folder is gone), `update_embeddings.bat` moved to `scripts\`, the graphical tools are in `gui/`.
- change: README — documents the wizard, the console and the repository layout, and `scripts\update_embeddings.bat` is described as the four steps it actually runs.

**5.2.0 - OCR for scanned PDFs**

- add: `--extract-missing` — OCRs scanned PDFs automatically (Tesseract), only on the pages without a text layer; the PDF is never modified.
- add: `--extract-missing --books <ids> --force-ocr` — re-OCRs PDFs with a bad text layer; the new text takes precedence in reading and search.
- add: install.ps1 — sets up OCR at first installation by default (Tesseract via winget, Italian/English language files); skip with `-NoOcr`.
- add: requirements-ocr.txt and `--download-ocr-langs` — the Python dependency for OCR, with Tesseract setup instructions for Windows, Linux and macOS.
- add: `--extract-missing` — books that fail are remembered and skipped until their files change; `--retry-failed` retries them.
- add: semantic index report — books without text show their extraction error.
- change: update_embeddings.bat — extracts missing texts (with OCR) before building the indexes.

**5.1.0 - Semantic index report and selective rebuild**

- add: `--embeddings-report` and calibre_semantic_index_report — list failed (with the error), missing, stale, empty, sparse, capped, no-text and orphan books, and check the index's integrity.
- add: `--build-embeddings --books <ids>` and `--retry-failed` — re-embed only selected books, leaving the rest of the index untouched.
- fix: `--build-embeddings` — an unexpected error on one book no longer stops the whole build; the error is recorded instead.
- fix: `--build-embeddings` — books deleted from Calibre are removed from the index even when their text is still in Calibre's full-text database.
- add: update_embeddings.bat — runs the semantic build, the figure index and the report in one step, passes options such as `--retry-failed` or `--books`, and saves the report to a file.

**5.0.0 - Library curation, hybrid semantic search and book distillation**

- add: calibre_quality_report — audits metadata: missing fields, file-name titles, invalid ISBNs, author name anomalies, unsorted author sort, author and tag variants, series gaps.
- add: calibre_search_semantic — hybrid search (default) fuses meaning and exact terms; `mode` selects hybrid, vector or keyword.
- add: calibre_search_semantic — `book_id` returns ranked passages inside one book, each with its chapter.
- change: semantic index — passages follow chapter boundaries, carry title, author and chapter as context, and cover the whole book (up to 1,500 passages).
- change: semantic index — the format changed; run `--build-embeddings` once to rebuild it, and the server reports an old index until then.
- add: calibre_search_semantic — front and back matter is demoted and labelled, and weak matches are flagged `low_confidence`.
- add: calibre_get_chapters — chapter map for every format, from the book's own TOC or from headings detected in the text.
- add: calibre_read_text — `chapter` reads one chapter and stops at its end.
- add: calibre_search_figures — finds figures across the library by caption and alt text; build the index with `--index-figures`.
- add: calibre_find_isbn — finds and validates the book's ISBN in its own text and compares it with the stored one.
- add: calibre_compare_books — compares possible duplicates field by field and suggests which record to keep.
- add: calibre_find_duplicates — groups whose books are in different languages are flagged as likely translations.
- add: calibre_check_overlap and `--legal-gate` — check that notes derived from books do not reproduce them.
- add: companion skills calibre-distill (one book) and calibre-distill-topic (one topic across several books).
- add: documentation — architecture section (components, modules, data stores, request flow, read-only guarantees) and full guides to curation, chapters, skills and the legal gate, in English and Italian.

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
