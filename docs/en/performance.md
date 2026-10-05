# Performance

[← README](../../README.md) · [Installation](installation.md) · [Tweaking and under the hood](tweaking.md) · [Skills](skills.md) · [FAQ and troubleshooting](faq.md) · **Performance**

🇬🇧 English · [🇮🇹 Italiano](../it/performance.md)

How fast the server is, how that was measured, what to expect on a real library, and which settings change it.
Every number in this manual comes from a **synthetic** library built by the benchmark that ships with the project
(`tests/bench_synthetic.py`), so you can repeat the measurements on your own machine.

**Contents**

- [How it was measured](#how-it-was-measured)
- [Results](#results)
- [Reading the numbers](#reading-the-numbers)
- [Sizing a real library](#sizing-a-real-library)
- [What affects performance](#what-affects-performance)
- [Measure it yourself](#measure-it-yourself)

## How it was measured

**The dataset.** The benchmark builds a Calibre-style library of 1,500 fake books and 524 MB of text. Words are
drawn from a 50,000-word pseudo-vocabulary with a Zipf frequency curve (so rare and common words behave as in natural
language), grouped in chapters. A few "needle" words appear in a known share of the books (`firewall` 5 %,
`kerberos` 2 %, `segmentation` 30 %, the phrase "lateral movement" 1.5 %), which makes rare-word and common-word
searches comparable. Metadata has 300 authors, 40 tags, two languages, EPUB (70 %) and PDF (30 %) records and ISBNs on
80 % of the books, and the tables carry the indexes a real Calibre library has.

**The machine.** Intel(R) Xeon(R) Processor @ 2.10GHz, 1 core(s), 4 GB RAM; Linux-6.18.44-fc-v70-x86_64-with-glibc2.39; Python 3.12.3; SQLite 3.45.1.

**The method.** Each operation runs 3 warm-up calls, then 30 timed calls; the table reports the **median**, the
**95th percentile** (the slowest typical call) and the **first call** (cold) separately. Tools are called in-process as
Python functions, so the figures are the server's own time: they exclude the MCP transport, the AI client and, above all,
the model. The initial index build is the server's own `--sync` (no per-document pause), timed by the server.

## Results

| Operation | Median | 95th percentile | First call |
|---|---|---|---|
| Initial index build (`--sync`, once) | 21.2 s | | 148 MB index |
| Incremental sync (1 text changed, 1 book removed) | 0.15 s | | |
| Metadata search, free words (`q`) | 7.8 ms | 11 ms | 8.1 ms |
| Metadata search, tag filter | 4.1 ms | 5.4 ms | 4.1 ms |
| Metadata search, author filter | 3.2 ms | 4.0 ms | 3.2 ms |
| Metadata search, Calibre syntax | 5.6 ms | 8.7 ms | 6.1 ms |
| Full-text, rare word (5 % of books), 10 books × 3 snippets | 50 ms | 59 ms | 53 ms |
| Full-text, common word (30 % of books), 10 books × 3 snippets | 25 ms | 26 ms | 25 ms |
| Full-text, exact phrase, 10 books × 3 snippets | 63 ms | 65 ms | 63 ms |
| Full-text, rare word, 50 books, no snippets | 2.5 ms | 3.3 ms | 3.5 ms |
| Full-text, common word, 50 books, no snippets | 3.0 ms | 3.2 ms | 3.1 ms |
| `calibre_read_text`, 6,000 characters from the middle of a book | 1.9 ms | 2.0 ms | 2.7 ms |
| `calibre_find_in_book`, 10 hits | 8.3 ms | 8.8 ms | 8.4 ms |
| Chapter map of one book (`calibre_get_chapters`) | 1.9 ms | 2.0 ms | 4.3 ms |
| Quality report, whole library | 27 ms | 62 ms | 29 ms |
| Duplicates search, whole library | 12 ms | 13 ms | 12 ms |
| Semantic hybrid search, 60,376 passages (`hash` backend) | 75 ms | 88 ms | 291 ms |
| Semantic index build, 100 books (`hash` backend) | 15.4 s | | 52 MB |

- The index is **148 MB for 524 MB of text (28 %)**: SQLite 3.45.1 builds the contentless full-text index, which does not store the text twice.
- *Incremental sync* changed one text and removed one book: a changed text is dropped and re-added (the server reports `added: 1`, `removed: 2`); it includes the default 5 ms pause per document.
- *First call* is the cold call; for the semantic search it includes loading the vectors into memory.
- The two semantic rows use the offline `hash` backend: they measure the index and the hybrid ranking over a realistic number of passages, **not** the speed of the real embedding model, which depends on your CPU (see [Sizing a real library](#sizing-a-real-library)).

The raw results of the run shown here are in [`tests/bench_reference.json`](../../tests/bench_reference.json).

## Reading the numbers

- **Everything here is in milliseconds, or seconds for one-off jobs.** An AI model takes much longer than that to write
  an answer, so the latency of a chat is dominated by the model, not by the server.
- **Snippets cost more than matching.** The same full-text search takes about 3.0 ms for 50 books without snippets and
  25–63 ms for 10 books with 3 snippets each: locating the best passages in the text is the work.
- **Not covered by these numbers:** on-demand extraction of PDF, LIT and MOBI books that Calibre has not indexed
  (`ebook-convert` can take seconds to minutes: the conversion timeout is 180 s by default, which is why Codex needs a
  longer `tool_timeout_sec`), OCR, the real embedding model, and slow storage (network shares, OneDrive).
- **Real libraries differ.** The synthetic text is more uniform than real books, so treat the results as a measure
  of scaling, not a promise.

## Sizing a real library

Measured, on the synthetic library: the full-text index takes 28 % of the text size, and the first sync runs at about
40 s per GB of text (the installer announces 30–60 s per GB). With older SQLite (before 3.43) the index is
not contentless and takes roughly the size of the text; `CALIBRE_MCP_STEMMING=1` roughly doubles the index.

**Estimates, not measured by the benchmark** (they scale the figures documented for the semantic index):

| Library | Passages (about 700 per book) | RAM for the vectors (about 384 bytes each) | Index on disk (about 0.6 MB per book) | First semantic build (1–2 h per 1,000 books) |
|---|---|---|---|---|
| 500 books | 350,000 | ~134 MB | ~300 MB | 0.5–1 h |
| 1,000 books | 700,000 | ~270 MB | ~600 MB | 1–2 h |
| 3,000 books | 2,100,000 | ~800 MB | ~1.8 GB | 3–6 h |

The build uses half of the CPU cores by default (`CALIBRE_MCP_EMBED_THREADS`), is incremental and resumable, and later
builds only process new or changed books. A book is capped at 1,500 passages (`CALIBRE_MCP_EMBED_MAX_CHUNKS`).

- **Embedding model:** about 220 MB downloaded once, 384-dimensional vectors, runs on the CPU.
- **OCR:** about 1–3 s per page on a CPU, so a 300-page scan takes roughly 5–15 minutes. OCR runs only in the batch command, never inside a chat request.
- **Disk in total:** the sidecar folder holds the full-text index, the optional semantic and figure indexes, the model and the OCR language files; deleting it is always safe.

## What affects performance

| Setting | Default | Effect |
|---|---|---|
| `CALIBRE_MCP_EMBED_THREADS` | half of the CPU cores | more threads build the semantic index faster and keep the PC busier |
| `CALIBRE_MCP_EMBED_MAX_CHUNKS` / `CALIBRE_MCP_EMBED_CHUNK` | 1,500 / 700 characters | fewer or longer passages mean a smaller, faster index; changing the size needs `--build-embeddings --rebuild` |
| `CALIBRE_MCP_THROTTLE_MS` | 5 ms | pause per document during background sync, to stay gentle on the PC (`--sync` has none) |
| `CALIBRE_MCP_SYNC_INTERVAL` | 600 s | how often the background sync runs; `0` = at startup only |
| `CALIBRE_MCP_STEMMING` | 0 | `1` adds a stemmed index: about twice the disk and a longer first sync |
| `CALIBRE_MCP_MAX_CHARS` | 12,000 | cap per read call: lower values cost the model fewer tokens |
| `CALIBRE_MCP_OCR_DPI` / `CALIBRE_MCP_OCR_PAGE_TIMEOUT` | 300 / 180 s | resolution of OCR page renders and per-page time limit |
| `CALIBRE_MCP_CONVERT_TIMEOUT` | 180 s | time limit of one `ebook-convert` run |

Outside the settings: **storage** (an SSD is much better than a network share or a OneDrive folder, which also adds
download latency), the **Python and SQLite versions** (3.12+ and SQLite 3.43+ give the compact index), the **PDF
backend** (`pymupdf` is faster than `pypdf`) and the **mix of formats** (LIT, MOBI and AZW3 books need Calibre's
converter the first time they are read). All settings are described in [Environment variables](tweaking.md#environment-variables).

## Measure it yourself

Run the benchmark (it needs numpy, which the semantic requirements install, and about 1 GB of free disk; it creates
its library in a temporary folder and removes it at the end):

```powershell
.venv\Scripts\python.exe tests\bench_synthetic.py                       # the documented run: 1,500 books, ~525 MB
.venv\Scripts\python.exe tests\bench_synthetic.py --books 300 --runs 10 # quicker
.venv\Scripts\python.exe tests\bench_synthetic.py --semantic-books 100 --json results.json
```

| Option | Default | Meaning |
|---|---|---|
| `--books` | 1500 | number of synthetic books |
| `--avg-kb` | 296 | average text size per book in KB (1,500 books ≈ 525 MB) |
| `--runs` | 30 | timed calls per operation |
| `--semantic-books` | 0 | also build the semantic index for this many books (offline `hash` backend) |
| `--json FILE` | | write the results as JSON |
| `--dir`, `--keep`, `--seed` | temp, off, 7 | working folder, keep the library afterwards, random seed |

To time your **own** library, call the tools the way the benchmark does (set `CALIBRE_LIBRARY` first):

```python
import sys, time
sys.argv = ["x"]; sys.path.insert(0, r"C:\Tools\mcp-calibre")
import calibre_mcp as m
m.set_libraries([m.detect_library()], m.default_data_dir())
t = time.perf_counter(); m.calibre_search_fulltext(query="firewall"); print(round((time.perf_counter() - t) * 1000, 1), "ms")
```

For long jobs, `--sync` reports its own duration, `--build-embeddings` prints progress per book, and `--embeddings-report`
shows what the semantic index contains. The [console](tweaking.md#console-graphical-manager) runs and times these jobs from its Maintenance tab.
