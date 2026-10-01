# mcp-calibre

[🇬🇧 English](README.md) · 🇮🇹 Italiano

Server MCP in sola lettura che dà a Claude (e a qualsiasi client MCP) accesso nativo a una libreria Calibre
locale: metadati, ricerca full-text su EPUB/PDF/MOBI/LIT/…, lettura per capitoli e pagine, highlight e note.
Trasporti: **stdio** (Claude Desktop) e **Streamable HTTP** (Claude Code, altri client, uso remoto).

## Design

| Aspetto | Scelta |
|---|---|
| Accesso ai dati | SQLite diretto su `metadata.db` / `full-text-search.db` in `mode=ro`: nessun subprocess `calibredb`, query in millisecondi |
| GUI di Calibre aperta | supportata: le connessioni read-only non vanno mai in conflitto con i lock di Calibre |
| Full-text | indice FTS5 sidecar sul testo **già estratto da Calibre** (EPUB/PDF/MOBI/DOCX…) |
| Formati leggibili | testo FTS di Calibre, poi estrazione on-demand: EPUB (integrata), PDF (PyMuPDF/pypdf), tutto il resto via `ebook-convert` |
| Trasporti | stdio e Streamable HTTP (stateless, risposte JSON, bearer auth, protezione DNS rebinding, TLS opzionale) |
| Portabilità | Windows/macOS/Linux, rilevamento automatico della libreria |
| Log | stderr + `%LOCALAPPDATA%\calibre-mcp\calibre-mcp.log`, query registrate solo a livello DEBUG |

## Perché un indice sidecar

La tabella FTS5 di Calibre usa un tokenizer custom (`calibre`) implementato nell'estensione C di Calibre, quindi
SQLite standard non può eseguire `MATCH` su di essa. La tabella `books_text`, che contiene il testo in chiaro,
è invece leggibile. Il server quindi:

1. legge `books_text` in sola lettura;
2. mantiene un indice FTS5 (`unicode61 remove_diacritics 2`) in `%LOCALAPPDATA%\calibre-mcp\<hash-libreria>\index.db`;
3. lo sincronizza **in modo incrementale** tramite `text_hash` (thread in background all'avvio, poi ogni 10 minuti).

Con SQLite ≥ 3.43 (Python 3.12+ da python.org) l'indice è *contentless* (`contentless_delete=1`) e non duplica
il testo. Con SQLite più vecchio ricade su FTS5 standard (occupa circa quanto il testo).

Misure su un dataset sintetico (1.500 libri, circa 525 MB di testo, un core di container):

| Operazione | Tempo |
|---|---|
| Costruzione iniziale dell'indice (una tantum) | ~30 s, indice da 193 MB |
| Sync incrementale (1 modifica, 1 rimozione) | 0,14 s |
| Ricerca full-text, 10 libri × 3 snippet | 80–90 ms |
| Ricerca full-text senza snippet, 50 libri | ~3 ms |
| Ricerca sui metadati | ~5 ms |
| `read_text` / `find_in_book` | 1–10 ms |

## Catena di estrazione del testo

Per ogni libro, in ordine:

1. testo FTS di Calibre (già estratto da Calibre, il più veloce);
2. cache locale;
3. estrazione on-demand:
   - EPUB: parser integrato, tollerante a container/OPF/spine/TOC rotti (i problemi diventano `warnings`);
   - PDF: PyMuPDF o pypdf, senza limite di pagine;
   - TXT: lettura diretta;
   - tutto il resto (LIT, MOBI, AZW3, RTF, DOC, ODT…): `ebook-convert` di Calibre.

Se un formato fallisce si passa al successivo. Il testo estratto viene messo in cache **e indicizzato**, quindi un
libro letto una volta diventa trovabile anche con `calibre_search_fulltext`. I PDF scansionati senza layer di
testo restituiscono un errore esplicito "OCR needed".

## Prerequisiti in Calibre

Abilita l'indicizzazione full-text in Calibre (pulsante **FT** accanto alla barra di ricerca). Calibre estrae il
testo in background, a bassa priorità e **solo mentre la GUI è aperta**. `calibre_library_status` mostra la
copertura (`texts_extracted`, `calibre_pending`, `extraction_errors`).

Per colmare il divario senza tenere Calibre aperto, usa l'estrazione batch (bassa priorità, riprendibile):

```powershell
.\.venv\Scripts\python.exe .\calibre_mcp.py --extract-missing --max-books 50
```

## Installazione (Windows)

```powershell
git clone https://github.com/jumpifequal/mcp-calibre C:\Tools\mcp-calibre
```

Clona o decomprimi il repo **fuori** dalla libreria Calibre e fuori da OneDrive (es. `C:\Tools\mcp-calibre`), poi:

```powershell
cd C:\Tools\mcp-calibre
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Library "D:\Books\Calibre Library" -Pdf pymupdf -Register
```

> **Non terminare il path di `-Library` con un backslash dentro le virgolette** (`"...\Calibre Library\"`):
> Windows legge `\"` come virgoletta escapata e inghiotte i parametri successivi. Lo script lo rileva e si ferma.

`-Register` modifica `%APPDATA%\Claude\claude_desktop_config.json` (con backup, UTF-8 senza BOM). Senza
`-Register` lo script stampa lo snippet JSON da incollare. Configurazione manuale:

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

Poi riavvia completamente Claude Desktop (esci dall'icona nella tray, non basta chiudere la finestra).

CLI: `python calibre_mcp.py --status` · `--sync` · `--extract-missing [--max-books N]` · `--library <path>` ·
`--transport http` (vedi sotto) · `--gen-token`.

## Trasporto HTTP

Endpoint Streamable HTTP (stateless, risposte JSON), per Claude Code, altri client MCP o un server condiviso in
LAN. Il bearer token è **obbligatorio**, salvo `--no-auth` esplicito, accettato solo su loopback.

```powershell
# una tantum: genera un token e salvalo per il tuo utente
$t = .\.venv\Scripts\python.exe .\calibre_mcp.py --gen-token
[Environment]::SetEnvironmentVariable('CALIBRE_MCP_HTTP_TOKEN', $t, 'User')
$env:CALIBRE_MCP_HTTP_TOKEN = $t

# avvio (bind di default 127.0.0.1:8765, endpoint /mcp)
.\.venv\Scripts\python.exe .\calibre_mcp.py --transport http
```

Client:

```powershell
# Claude Code
claude mcp add --transport http calibre http://127.0.0.1:8765/mcp --header "Authorization: Bearer $env:CALIBRE_MCP_HTTP_TOKEN"
```

Per Claude Desktop stdio resta l'opzione più semplice. Se vuoi che Desktop usi il server HTTP (ad es. un'unica
istanza condivisa), fai da ponte con `mcp-remote` (richiede Node.js):

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

La forma `Authorization:${AUTH}` evita un problema noto con gli spazi dentro `args` su Windows.

Avvio al logon in background (senza finestra console):

```powershell
$repo = 'C:\Tools\mcp-calibre'
$act  = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" -Argument "`"$repo\calibre_mcp.py`" --transport http" -WorkingDirectory $repo
Register-ScheduledTask -TaskName 'calibre-mcp' -Action $act -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0)
```

Esposizione in LAN (sconsigliata senza TLS):

```powershell
.\.venv\Scripts\python.exe .\calibre_mcp.py --transport http --host 0.0.0.0 --allowed-host mybox.lan:8765 `
    --ssl-certfile .\cert.pem --ssl-keyfile .\key.pem
```

| Opzione | Default | Note |
|---|---|---|
| `--host` | `127.0.0.1` | un bind non-loopback senza TLS genera un warning |
| `--port` | `8765` | |
| `--path` | `/mcp` | |
| `--allowed-host` | nomi loopback | allow-list dell'header Host (protezione DNS rebinding); `nome:*` = qualsiasi porta. Obbligatorio con `0.0.0.0` |
| `--allowed-origin` | nessuno | Origin browser ammessi; le richieste con altri Origin ricevono 403 |
| `--ssl-certfile` / `--ssl-keyfile` | — | TLS nativo (oppure un reverse proxy davanti) |
| `--no-auth` | off | solo su loopback |

I custom connector di claude.ai chiamano il server dal cloud di Anthropic, quindi richiedono un endpoint HTTPS
pubblico e OAuth, non un token statico: questo server non è pensato per quel tipo di esposizione.

## Tool

| Tool | Scopo |
|---|---|
| `calibre_search_books` | Ricerca sui metadati: testo libero, title/author/tag/series/publisher/language/format/identifier, rating, date, `has_annotations`, ordinamento, paginazione |
| `calibre_search_fulltext` | Ricerca nel contenuto, ranking BM25, insensibile agli accenti. Modalità `all`/`any`/`phrase`/`raw` (FTS5: `NEAR`, `OR`, `prefix*`). I filtri sui metadati restringono i libri candidati; gli snippet riportano un `offset` |
| `calibre_get_book` | Metadati completi, identifier, descrizione, formati, testo disponibile per formato, errori di estrazione di Calibre |
| `calibre_read_text` | Finestra di testo per offset (opzionalmente centrata sull'offset di uno snippet) |
| `calibre_find_in_book` | Ricerca keyword-in-context dentro un singolo libro, paginata |
| `calibre_get_toc` | Indice EPUB (nav/NCX → indici di sezione) o outline PDF + numero di pagine |
| `calibre_read_section` | Un capitolo EPUB o un intervallo di pagine PDF (max 30 per chiamata), per citazioni precise |
| `calibre_list_facets` | Autori/tag/serie/editori/lingue/formati con il numero di libri |
| `calibre_get_annotations` | Highlight, note e bookmark del viewer di Calibre (un libro o tutta la libreria) |
| `calibre_library_status` | Diagnostica: copertura FTS di Calibre, stato del sidecar, backend PDF, path di `ebook-convert`, versione SQLite |

## Variabili d'ambiente

| Variabile | Default |
|---|---|
| `CALIBRE_LIBRARY` | rilevata da `%APPDATA%\calibre\global.py.json`, poi `~\Calibre Library` |
| `CALIBRE_MCP_DATA` | `%LOCALAPPDATA%\calibre-mcp` |
| `CALIBRE_MCP_MAX_CHARS` | `12000` (limite per singola lettura: controlla il consumo di token) |
| `CALIBRE_MCP_SYNC_INTERVAL` | `600` s (`0` = solo all'avvio) |
| `CALIBRE_MCP_THROTTLE_MS` | `5` ms di pausa per documento indicizzato |
| `CALIBRE_EBOOK_CONVERT` | rilevato: PATH, poi `Calibre2\ebook-convert.exe` sia in `Program Files` sia in `Program Files (x86)` (anche da processi a 32 bit, via `%ProgramW6432%`) |
| `CALIBRE_MCP_CONVERT_TIMEOUT` | `180` s per conversione |
| `CALIBRE_MCP_LOG_LEVEL` | `INFO` (`DEBUG` registra anche le query) |
| `CALIBRE_MCP_HTTP_TOKEN` | — (obbligatorio per `--transport http`, min 24 caratteri) |

## Troubleshooting

| Sintomo | Verifica |
|---|---|
| Nessun tool `calibre_*` in Claude | `mcpServers.calibre` presente nella config; Desktop riavviato completamente; `%APPDATA%\Claude\logs\mcp-server-calibre.log` |
| Il server non parte | esegui `python calibre_mcp.py --status` con gli stessi path della config |
| La ricerca full-text trova poco | `calibre_library_status`: `texts_extracted` basso → lascia Calibre aperto o lancia `--extract-missing` |
| I libri LIT/MOBI falliscono | `ebook_convert` è `null` nello status → imposta `CALIBRE_EBOOK_CONVERT` |
| "OCR needed" | PDF scansionato senza layer di testo: fai l'OCR (es. OCRmyPDF) e reinseriscilo in Calibre |

## Note di sicurezza

- **HTTP**: bind su loopback di default; bearer token statico confrontato in tempo costante (min 24 caratteri, `--gen-token` = 256 bit); validazione di Host/Origin contro il DNS rebinding; nessun header `Server`; `--no-auth` rifiutato fuori da loopback. Il token dà accesso in lettura all'intera libreria: trattalo come una password. Senza TLS, token e contenuto dei libri viaggiano in chiaro sulla rete.
- **Read-only by design**: connessioni SQLite in `mode=ro` con `PRAGMA query_only`; nessun tool di scrittura, nessuna shell. L'unico subprocess è `ebook-convert` (argv a lista, senza shell, timeout, stdout catturato, priorità below-normal, directory di output temporanea).
- **Confinamento dei path**: i path derivati dal DB vengono risolti e rifiutati se escono dalla root della libreria.
- **Query FTS**: in `all`/`any`/`phrase` ogni token è quotato, quindi gli operatori FTS5 nell'input non possono cambiare la semantica della query; `raw` è opt-in e gli errori di sintassi sono gestiti.
- **Parsing di contenuto non fidato**: gli EPUB hanno limiti di dimensione per membro e totali (anti zip-bomb) e confinamento dei path nell'archivio; l'XML passa da `defusedxml`; i PDF vengono analizzati solo on-demand. PyMuPDF e i convertitori di Calibre sono codice nativo (superficie d'attacco memory-safety): se il rischio non è accettabile, usa `-Pdf pypdf` o `none`, lascia `ebook-convert` non disponibile e affidati all'indicizzazione di Calibre.
- **Prompt injection indiretta**: testo dei libri e annotazioni sono contenuto di terzi restituito al modello. Le `instructions` del server lo dichiarano esplicitamente, ma non è un controllo forte: evita di combinare questo server, nella stessa sessione, con tool ad alto impatto (invio mail, shell, browser).
- **Licenze**: PyMuPDF è AGPL-3.0; pypdf è BSD.

## Limitazioni note

- Le colonne custom di Calibre (tabelle `custom_column_N`) non sono esposte.
- Una libreria per istanza del server (per più librerie: più voci in `mcpServers` con `CALIBRE_LIBRARY` diversi).
- Libreria su share di rete o OneDrive: funziona in sola lettura, ma con latenze maggiori ed effetti collaterali della sincronizzazione per Calibre stesso.
- Gli offset restituiti da `search_fulltext` si riferiscono al testo del `format` indicato, non alle sezioni EPUB estratte on-demand.

## Background

L'idea di esporre una libreria Calibre via MCP è stata esplorata per la prima volta dal progetto in bash
[trieloff/calibre-mcp](https://github.com/trieloff/calibre-mcp). Questo progetto è un'implementazione
indipendente e non ne condivide il codice.

## Licenza

Apache-2.0.
