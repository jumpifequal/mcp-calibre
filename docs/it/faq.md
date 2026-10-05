# FAQ e risoluzione dei problemi

[← README](../../README.it.md) · [Installazione](installation.md) · [Personalizzazione e funzionamento interno](tweaking.md) · [Skill](skills.md) · **FAQ e risoluzione dei problemi** · [Prestazioni](performance.md)

[🇬🇧 English](../en/faq.md) · 🇮🇹 Italiano

Cerca qui sotto il tuo sintomo. Prima i problemi di installazione e configurazione, poi quelli durante l'uso del
server, poi quelli degli strumenti grafici, infine i limiti noti. Se non trovi nulla, vedi
[Ancora bloccato?](#ancora-bloccato).

**Indice**

- [Le basi](#le-basi)
- [Problemi di installazione e configurazione](#problemi-di-installazione-e-configurazione)
- [Problemi durante l'uso](#problemi-durante-luso)
- [Problemi della procedura guidata e della console](#problemi-della-procedura-guidata-e-della-console)
- [Limitazioni note](#limitazioni-note)
- [Ancora bloccato?](#ancora-bloccato)

## Le basi

### Devo avviare io il server?

Dipende dalla connessione. Con **stdio** (Claude Desktop, app desktop ChatGPT, Codex) non avvii nulla: il client lancia il server quando serve e lo ferma dopo, quindi non c'è nessuna finestra da tenere aperta, e *Start server* della console non serve. Solo **Streamable HTTP** (per esempio Claude Code, o un server condiviso da più client) richiede un server che avvii tu: `calibre_mcp.py --transport http`, un'attività pianificata, oppure *Start server* nella console. La console è opzionale in ogni caso, e i lavori di manutenzione (`--sync`, `--build-embeddings`, `--extract-missing`…) non richiedono mai un server in esecuzione. Vedi [Collega il tuo client AI](installation.md#collega-il-tuo-client-ai).

### Modifica la mia libreria Calibre?

No. I database di Calibre vengono aperti in sola lettura (`mode=ro` con `PRAGMA query_only`), i file dei libri vengono solo letti e non esistono tool di scrittura. Il server scrive solo la propria cache (il sidecar) e il proprio log. I tool di curation (report di qualità, duplicati, ISBN) segnalano i problemi; li correggi tu in Calibre.

### Calibre deve essere in esecuzione?

No. Le connessioni in sola lettura non entrano mai in conflitto con i lock di Calibre, quindi il server funziona con Calibre aperto o chiuso. Un'avvertenza: Calibre estrae il testo dei libri in background, a bassa priorità e solo mentre la sua finestra è aperta. Per coprire i libri che non ha elaborato, esegui `--extract-missing` (vedi [Prerequisiti in Calibre](installation.md#prerequisiti-in-calibre)).

### I miei dati escono dal mio computer?

Il server gira sul tuo computer e non ha accesso alla rete al momento delle query (il modello di embedding viene scaricato una volta sola durante l'installazione; costruire l'indice semantico e ogni query semantica avvengono in locale). Ma ciò che un tool restituisce va al tuo client AI: gli snippet, i capitoli e i metadati che l'assistente richiede arrivano al servizio AI che hai scelto, come con qualsiasi server MCP. Le immagini mostrate con `calibre_show_images` vanno alla vista nella chat, non nel contesto del modello.

### Quali lingue funzionano?

La ricerca nei metadati e quella full-text sono lessicali: la query deve essere nella lingua dei libri (una query in italiano non trova testo inglese), quindi all'assistente viene detto di tradurla o di combinare le traduzioni. La ricerca semantica è multilingue: una domanda in italiano trova anche passaggi in inglese. Lo stemming è solo inglese. L'OCR usa di default `ita` ed `eng`; aggiungi altre lingue con `--download-ocr-langs`.

### Quali sistemi e client sono supportati?

Windows 10/11 per intero (procedura guidata, installer, console); macOS e Linux con l'installazione manuale. Client: Claude Desktop, Claude Code, app desktop ChatGPT, Codex CLI ed estensione IDE, e qualsiasi client MCP via stdio o HTTP. ChatGPT sul web e i connettori personalizzati di claude.ai non possono usarlo. Vedi [Collega il tuo client AI](installation.md#collega-il-tuo-client-ai).

### Dove tiene i suoi dati?

In `%LOCALAPPDATA%\calibre-mcp\<hash-libreria>\` per ogni libreria (`index.db`, `embeddings.db`, `figures.db`, `converted/`), più `models/`, `tessdata/` e `calibre-mcp.log` nella cartella sopra. Imposta `CALIBRE_MCP_DATA` per spostarla. Cancellarla è sempre sicuro: tutto si può ricostruire dalla libreria. Vedi [Archivi di dati](tweaking.md#architettura).

### Cosa faccio se aggiungo, modifico o elimino un libro in Calibre?

I metadati seguono Calibre subito; gli indici del testo si aggiornano da soli, tranne quelli semantico e delle figure, che aggiorni con un comando. Cosa succede dipende da ciò che hai fatto:

| In Calibre… | Ricerche sui metadati | Ricerca full-text | Ricerca semantica |
|---|---|---|---|
| **aggiungi** un libro | lo vedono subito | dopo che Calibre ha estratto il testo (indicizzazione FT, con la finestra aperta), oppure dopo `--extract-missing`; poi alla sincronizzazione successiva | esegui `--build-embeddings` |
| **modifichi i suoi metadati** (titolo, autori, tag, colonne personalizzate…) | subito (le definizioni delle colonne personalizzate si aggiornano entro 30 s) | nulla da fare | nulla da fare: i risultati mostrano il titolo e gli autori attuali |
| **cambi il suo file** (sostituisci o converti un formato) | subito | Calibre riestrae il testo e la sincronizzazione successiva lo recepisce | esegui `--build-embeddings`: il libro risulta `stale` e viene aggiornato |
| **elimini** un libro | sparisce subito | rimosso alla sincronizzazione successiva; fino ad allora può ancora comparire come risultato senza titolo | rimosso dal successivo `--build-embeddings` completo; fino ad allora può comparire senza titolo, e `--embeddings-report` lo elenca come `orphan` |

La **sincronizzazione** dell'indice full-text gira in background nel server, all'avvio e ogni 10 minuti finché è in esecuzione (`CALIBRE_MCP_SYNC_INTERVAL`, `0` = solo all'avvio). Con stdio il server gira solo mentre il tuo client AI lo tiene aperto, quindi riavviare il client forza anche una sincronizzazione; oppure esegui tu `--sync`. I libri che Calibre non ha indicizzato, PDF scansionati compresi, sono coperti da `--extract-missing`. L'indice delle figure si aggiorna con `--index-figures`, che è incrementale.

Dopo una serie di modifiche la routine più semplice è `scripts\update_embeddings.bat`: esegue testi mancanti con OCR, costruzione semantica, indice delle figure e report, in quest'ordine. Per vedere a che punto sei, chiedi all'assistente `calibre_library_status` (`texts_extracted`, `calibre_pending`, e `pending` e `last_sync` del sidecar) oppure esegui `--embeddings-report` (`missing`, `stale`, `orphan`). Altro in [Prerequisiti in Calibre](installation.md#prerequisiti-in-calibre) e [Ricerca semantica](tweaking.md#funzioni-opzionali).

### Quanto disco, memoria e tempo servono?

L'indice full-text è una frazione della dimensione del testo e si costruisce in secondi ogni cento megabyte; l'indice semantico è la parte pesante (ore di CPU per una prima costruzione su una libreria grande). Numeri e messa a punto sono in [Prestazioni](performance.md#dimensionare-una-libreria-reale).

## Problemi di installazione e configurazione

La prima tabella raccoglie i sintomi di configurazione già coperti dall'installer; le domande qui sotto aggiungono il resto.

| Sintomo | Verifica |
|---|---|
| Nessun tool `calibre_*` in Claude | `mcpServers.calibre` presente nella config; Desktop riavviato completamente; `%APPDATA%\Claude\logs\mcp-server-calibre.log` |
| Il server non parte | esegui `python calibre_mcp.py --status` con gli stessi path della config |
| "Semantic search dependencies are missing" | Sono state installate in un altro Python: esegui il comando stampato nell'errore (usa il `python.exe` del server), poi riavvia il client |
| Download del modello fallito durante il setup | Verifica rete/`HTTPS_PROXY`, poi `.venv\Scripts\python.exe calibre_mcp.py --download-model`; offline: vedi [Modello per la ricerca semantica](tweaking.md#modello-per-la-ricerca-semantica) |
| Codex/ChatGPT: timeout di un tool | Alza `tool_timeout_sec` in `config.toml` (la conversione on-demand di LIT/MOBI può richiedere minuti) |

### L'installer dice "Python >= 3.10 required"

Installa Python da python.org, non dal Microsoft Store; si consiglia la 3.12 o successiva (SQLite 3.43+ dà un indice full-text contentless che occupa circa un terzo dello spazio su disco). L'installer usa il launcher `py` se presente, altrimenti `python`.

### "Semantic search skipped: it needs 64-bit Python"

Il runtime degli embedding non ha build a 32 bit. Installa Python a 64 bit e rilancia l'installer, oppure ignora l'avviso: il server di base funziona anche senza ricerca semantica.

### Il percorso di `-Library` ha inghiottito `-Pdf` e `-Register` ("-Library contains a quote")

Un percorso che termina con un backslash dentro le virgolette (`"...\Calibre Library\"`) fa leggere a Windows `\"` come virgoletta escapata. Togli il backslash finale. Lo script rileva il problema e si ferma; la procedura guidata toglie il backslash al posto tuo.

### "metadata.db not found in …"

`-Library` deve essere la cartella della libreria stessa, quella che contiene `metadata.db`: non la sua cartella superiore e non una sottocartella.

### Avviso: il repository è dentro OneDrive e/o dentro la libreria Calibre

La cartella `.venv` contiene migliaia di file che OneDrive sincronizzerebbe, e Calibre segnalerebbe una cartella in più nella sua libreria. Sposta il repository, per esempio in `C:\Tools\mcp-calibre`.

### Avviso: la libreria è in una cartella OneDrive

Imposta la cartella della libreria su "Mantieni sempre su questo dispositivo"; altrimenti leggere un libro forza il download del file. Il server funziona in sola lettura su una libreria OneDrive o di rete, ma con latenza maggiore e con effetti di sincronizzazione per Calibre stesso.

### Tesseract manca, o winget non è disponibile

L'installer esegue `winget install --id UB-Mannheim.TesseractOCR -e` (Windows può chiedere conferma). Senza winget, installa Tesseract da <https://github.com/UB-Mannheim/tesseract/wiki>, poi esegui `calibre_mcp.py --download-ocr-langs ita,eng`. L'OCR richiede anche PyMuPDF, quindi viene saltato con `-Pdf pypdf` o `-Pdf none`. Ogni parte opzionale è non bloccante: il server di base si installa comunque.

### Il server si rifiuta di partire via HTTP

Ogni rifiuto indica la sua causa. "Set CALIBRE_MCP_HTTP_TOKEN (generate one with --gen-token), or use --no-auth on a loopback bind": nessun token configurato. "CALIBRE_MCP_HTTP_TOKEN too short (min 24 chars)": generane uno con `--gen-token`. "--no-auth is only allowed on a loopback bind": togli `--no-auth` o usa il bind su `127.0.0.1`. "Binding to all interfaces: list the names clients will use with --allowed-host": aggiungi `--allowed-host nome:porta`. Vedi [Trasporto HTTP](installation.md#trasporto-http).

### Un client HTTP riceve 401 o 403

401 significa bearer token mancante o sbagliato (il server registra `HTTP 401 from <indirizzo> <percorso>`). Una richiesta con un Origin del browser non consentito riceve 403 (`--allowed-origin`), e un header Host che non è nella lista consentita viene rifiutato (`--allowed-host`).

### Il download del modello di embedding è fallito, o le dipendenze sembrano mancare

Vedi la prima tabella qui sopra per i messaggi esatti. Offline, copia la cartella del modello da un altro computer nella directory della cache, oppure usa `CALIBRE_MCP_EMBED_BACKEND=hash` (un ripiego lessicale, non semantico): vedi [Modello per la ricerca semantica](tweaking.md#modello-per-la-ricerca-semantica).

## Problemi durante l'uso

| Sintomo | Verifica |
|---|---|
| La ricerca full-text trova poco | `calibre_library_status`: `texts_extracted` basso → lascia Calibre aperto o lancia `--extract-missing` |
| I libri LIT/MOBI falliscono | `ebook_convert` è `null` nello status → imposta `CALIBRE_EBOOK_CONVERT` |
| "OCR needed" / PDF scansionato senza testo | `install.ps1` (oppure `--download-ocr-langs ita,eng` dopo aver installato Tesseract), poi `--extract-missing`; un PDF con un livello di testo illeggibile: `--extract-missing --books <id> --force-ocr` |
| `--build-embeddings` ha segnalato libri falliti | `--embeddings-report` li mostra con l'errore; correggi, poi `--build-embeddings --retry-failed` |
| "The semantic index was built by an older version" | indice della 4.x: esegui una volta `.venv\Scripts\python.exe calibre_mcp.py --build-embeddings` |
| Risultati semantici tutti `low_confidence` | il tema potrebbe non essere nella libreria, o i libri pertinenti non sono ancora indicizzati: controlla `semantic_index.books` in `calibre_library_status` |
| "Figure index not built" / la ricerca delle figure non trova nulla | esegui `calibre_mcp.py --index-figures`; vengono indicizzate solo le figure di EPUB e PDF con didascalia o testo alternativo |
| Mappa con un solo capitolo o titoli strani | il libro non ha TOC né heading riconoscibili; usa `calibre_read_text` per offset, o `calibre_get_toc` per le sezioni EPUB |
| Legal gate FAIL | il report indica il controllo e, per `longest_run`, il testo copiato: riscrivilo, poi rilancia |

### Una ricerca di una parola italiana non trova nulla nei miei libri inglesi

La ricerca full-text è lessicale, quindi la query deve usare la lingua dei libri. Chiedi all'assistente di tradurre la query, o di combinare le traduzioni (`mode="any"`). Per la ricerca per significato usa `calibre_search_semantic`, che è multilingue.

### Le immagini non compaiono nella chat

`calibre_show_images` usa l'estensione MCP Apps, supportata tra gli altri da Claude (web e desktop) e ChatGPT. Un client che non la supporta mostra solo il riepilogo testuale, che dice al modello di riprovare con `also_for_model=true` (piccole miniature per il modello, dentro il blocco del tool). Su alcune build di Claude Desktop per Windows sono stati segnalati problemi di rendering; il ripiego copre anche quelli. Vedi [Mostrare le immagini nella chat](tweaking.md#mostrare-le-immagini-nella-chat).

### La prima query semantica dopo l'avvio è più lenta

La prima query semantica carica i vettori in memoria: nel benchmark ha richiesto circa 291 ms contro circa 75 ms per le successive. Subito dopo una prima installazione la sincronizzazione in background può essere ancora impegnata a costruire l'indice full-text (circa 21 s per 524 MB di testo nel benchmark; di default fa una pausa di 5 ms per documento, `CALIBRE_MCP_THROTTLE_MS`), quindi le ricerche funzionano ma coprono solo ciò che è già indicizzato: `calibre_library_status` mostra lo stato. I tempi tipici sono in [Prestazioni](performance.md#risultati).

## Problemi della procedura guidata e della console

### La procedura guidata dice "Blocking problem found"

Solo tre cose bloccano la procedura: `install.ps1` o `calibre_mcp.py` assenti dalla cartella di installazione, oppure Python non trovato o precedente alla 3.10. Correggi e premi *Re-check*. Tutto il resto (OneDrive, Tesseract, `ebook-convert`) è un avviso.

### Un'opzione della procedura guidata è disattivata (grigia)

Le opzioni derivano dai parametri dichiarati da `install.ps1`. Se la tua copia dell'installer non ha un parametro (per esempio `-NoOcr`), la procedura disattiva quell'opzione invece di passare un parametro sconosciuto.

### La console dice "calibre_mcp.py not found"

Cerca nella cartella impostata come *Server folder* in Settings, poi nella propria cartella, poi nella cartella superiore a `gui/`. Imposta *Server folder* sulla radice del repository.

### Il pulsante Start è disattivato e lo stato dice STDIO

È normale: in modalità stdio il client AI avvia e possiede il server (tu non devi avviare nulla) e la pipe trasporta il protocollo, quindi la console non può supervisionarlo. Passa la scheda Transport a HTTP solo se esegui un server HTTP. Per stdio usa *Self-test* e *Follow Claude Desktop's MCP log*. Vedi [Console](tweaking.md#console-gestione-grafica).

### La console si rifiuta di avviare il server

La scheda Transport indica il motivo. Blocca un token mancante o corto (sotto i 24 caratteri; premi *Generate*), `--no-auth` fuori dal loopback, un bind non loopback senza host consentito e TLS con certificato ma senza chiave. Un bind non loopback senza TLS è consentito con un avviso.

### Le mie variabili impostate con `set` vengono ignorate dalla console

Di default la console rimuove le variabili che gestisce dall'ambiente ereditato, così il profilo è l'unica fonte di verità. Usa *Import from environment* (avvia la console dalla shell in cui hai eseguito `set`), oppure togli la spunta a *Isolate from the system environment*.

### Dove tiene la console le impostazioni e il token?

In `%LOCALAPPDATA%\calibre-mcp-console\profiles.json`. Il token è protetto con DPAPI di Windows per l'utente Windows corrente: un profilo copiato su un altro account o computer non può decifrarlo, quindi genera lì un nuovo token.

## Limitazioni note

- Le colonne custom composite (calcolate da template) non sono leggibili: Calibre non ne salva i valori.
- La sintassi di ricerca è un ampio sottoinsieme di quella di Calibre: niente `template:`, `marked:`, `ondevice:`, e il match gerarchico dei tag (`tag:.parent`) non è gestito in modo speciale.
- Lo stemming è solo inglese (Porter).
- Il rilevamento dei capitoli senza TOC è euristico (parole chiave, numerazione, righe brevi in maiuscolo); impaginazioni insolite possono dare una mappa grossolana.
- La ricerca delle figure copre EPUB e PDF; le figure dentro LIT/MOBI/AZW3 si raggiungono libro per libro con `calibre_list_figures`, non tramite l'indice di libreria.
- La qualità dell'OCR dipende dalla scansione: scrittura a mano, impaginazioni a più colonne e tabelle escono imperfette con Tesseract.
- Libreria su share di rete o OneDrive: funziona in sola lettura, ma con latenze maggiori ed effetti collaterali della sincronizzazione per Calibre stesso.
- Gli offset restituiti da `search_fulltext` si riferiscono al testo del `format` indicato, non alle sezioni EPUB estratte on-demand.

## Ancora bloccato?

Raccogli questo prima di chiedere aiuto; risponde alla maggior parte delle domande:

1. `.venv\Scripts\python.exe calibre_mcp.py --status`: libreria, versioni, backend, copertura del testo.
2. Nel tuo client AI, chiedi `calibre_library_status`: sidecar, indici stemmed e semantico, funzioni attive.
3. I log: `%LOCALAPPDATA%\calibre-mcp\calibre-mcp.log` (il server) e, per Claude Desktop,
   `%APPDATA%\Claude\logs\mcp-server-calibre.log`. Imposta `CALIBRE_MCP_LOG_LEVEL=DEBUG` per più dettagli; nota che
   DEBUG registra anche le tue query, quindi rivedi il log prima di condividerlo. Il pulsante *Save* della console
   scrive il suo log in un file.
4. Le versioni di Windows e Python, e il `server_version` mostrato da `--status`.

Poi apri una issue su <https://github.com/jumpifequal/mcp-calibre/issues> con i passaggi che hanno portato al
problema e ciò che hai raccolto.
