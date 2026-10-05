# Prestazioni

[← README](../../README.it.md) · [Installazione](installation.md) · [Personalizzazione e funzionamento interno](tweaking.md) · [Skill](skills.md) · [FAQ e risoluzione dei problemi](faq.md) · **Prestazioni**

[🇬🇧 English](../en/performance.md) · 🇮🇹 Italiano

Quanto è veloce il server, come è stato misurato, cosa aspettarsi su una libreria reale e quali impostazioni lo
cambiano. Ogni numero di questo manuale viene da una libreria **sintetica** costruita dal benchmark incluso nel
progetto (`tests/bench_synthetic.py`), quindi puoi ripetere le misure sul tuo computer.

**Indice**

- [Come è stato misurato](#come-è-stato-misurato)
- [Risultati](#risultati)
- [Come leggere i numeri](#come-leggere-i-numeri)
- [Dimensionare una libreria reale](#dimensionare-una-libreria-reale)
- [Cosa influisce sulle prestazioni](#cosa-influisce-sulle-prestazioni)
- [Misurala tu](#misurala-tu)

## Come è stato misurato

**Il dataset.** Il benchmark costruisce una libreria in stile Calibre con 1.500 libri finti e 524 MB di testo. Le parole sono
estratte da un pseudo-vocabolario di 50.000 parole con una curva di frequenza di Zipf (così parole rare e comuni si
comportano come nel linguaggio naturale), raggruppate in capitoli. Alcune parole "ago" compaiono in una quota nota
dei libri (`firewall` 5 %, `kerberos` 2 %, `segmentation` 30 %, la frase "lateral movement" 1,5 %), il che rende
confrontabili le ricerche di parole rare e comuni. I metadati hanno 300 autori, 40 tag, due lingue, record EPUB (70 %)
e PDF (30 %) e ISBN sull'80 % dei libri, e le tabelle hanno gli indici di una vera libreria Calibre.

**La macchina.** Intel(R) Xeon(R) Processor @ 2.10GHz, 1 core, 4 GB RAM; Linux-6.18.44-fc-v70-x86_64-with-glibc2.39; Python 3.12.3; SQLite 3.45.1.

**Il metodo.** Ogni operazione esegue 3 chiamate di riscaldamento, poi 30 chiamate misurate; la tabella riporta la **mediana**, il
**95° percentile** (la chiamata tipica più lenta) e la **prima chiamata** (a freddo) separatamente. I tool sono chiamati
in-process come funzioni Python, quindi i valori sono il tempo del server: escludono il trasporto MCP, il client AI e,
soprattutto, il modello. La costruzione iniziale dell'indice è il `--sync` del server (senza pausa per documento),
cronometrato dal server stesso.

## Risultati

| Operazione | Mediana | 95° percentile | Prima chiamata |
|---|---|---|---|
| Costruzione iniziale dell'indice (`--sync`, una tantum) | 21,2 s | | 148 MB di indice |
| Sincronizzazione incrementale (1 testo modificato, 1 libro rimosso) | 0,15 s | | |
| Ricerca nei metadati, parole libere (`q`) | 7,8 ms | 11 ms | 8,1 ms |
| Ricerca nei metadati, filtro per tag | 4,1 ms | 5,4 ms | 4,1 ms |
| Ricerca nei metadati, filtro per autore | 3,2 ms | 4,0 ms | 3,2 ms |
| Ricerca nei metadati, sintassi di Calibre | 5,6 ms | 8,7 ms | 6,1 ms |
| Full-text, parola rara (5 % dei libri), 10 libri × 3 snippet | 50 ms | 59 ms | 53 ms |
| Full-text, parola comune (30 % dei libri), 10 libri × 3 snippet | 25 ms | 26 ms | 25 ms |
| Full-text, frase esatta, 10 libri × 3 snippet | 63 ms | 65 ms | 63 ms |
| Full-text, parola rara, 50 libri, senza snippet | 2,5 ms | 3,3 ms | 3,5 ms |
| Full-text, parola comune, 50 libri, senza snippet | 3,0 ms | 3,2 ms | 3,1 ms |
| `calibre_read_text`, 6.000 caratteri dal centro di un libro | 1,9 ms | 2,0 ms | 2,7 ms |
| `calibre_find_in_book`, 10 risultati | 8,3 ms | 8,8 ms | 8,4 ms |
| Mappa dei capitoli di un libro (`calibre_get_chapters`) | 1,9 ms | 2,0 ms | 4,3 ms |
| Report di qualità, intera libreria | 27 ms | 62 ms | 29 ms |
| Ricerca dei duplicati, intera libreria | 12 ms | 13 ms | 12 ms |
| Ricerca semantica ibrida, 60.376 passaggi (backend `hash`) | 75 ms | 88 ms | 291 ms |
| Costruzione indice semantico, 100 libri (backend `hash`) | 15,4 s | | 52 MB |

- L'indice è **148 MB per 524 MB di testo (28 %)**: SQLite 3.45.1 costruisce l'indice full-text contentless, che non memorizza due volte il testo.
- La *sincronizzazione incrementale* ha modificato un testo e rimosso un libro: un testo modificato viene eliminato e riaggiunto (il server riporta `added: 1`, `removed: 2`); include la pausa di 5 ms per documento prevista di default.
- La *prima chiamata* è quella a freddo; per la ricerca semantica include il caricamento dei vettori in memoria.
- Le due righe semantiche usano il backend offline `hash`: misurano l'indice e il ranking ibrido su un numero realistico di passaggi, **non** la velocità del vero modello di embedding, che dipende dalla tua CPU (vedi [Dimensionare una libreria reale](#dimensionare-una-libreria-reale)).

I risultati grezzi dell'esecuzione mostrata qui sono in [`tests/bench_reference.json`](../../tests/bench_reference.json).

## Come leggere i numeri

- **Tutto qui è in millisecondi, o in secondi per i lavori una tantum.** Un modello AI impiega molto più tempo a scrivere
  una risposta, quindi la latenza di una chat è dominata dal modello, non dal server.
- **Gli snippet costano più del confronto.** La stessa ricerca full-text richiede circa 3,0 ms per 50 libri senza snippet e
  25–63 ms per 10 libri con 3 snippet ciascuno: il lavoro è individuare i passaggi migliori nel testo.
- **Non coperto da questi numeri:** l'estrazione on-demand di libri PDF, LIT e MOBI che Calibre non ha indicizzato
  (`ebook-convert` può impiegare da secondi a minuti: il timeout di conversione è 180 s di default, ed è per questo che
  Codex richiede un `tool_timeout_sec` più lungo), l'OCR, il vero modello di embedding e l'archiviazione lenta
  (condivisioni di rete, OneDrive).
- **Le librerie reali sono diverse.** Il testo sintetico è più uniforme dei libri veri, quindi considera i risultati
  una misura di scalabilità, non una promessa.

## Dimensionare una libreria reale

Misurato, sulla libreria sintetica: l'indice full-text occupa il 28 % della dimensione del testo, e la prima
sincronizzazione procede a circa 40 s per GB di testo (l'installer annuncia 30–60 s per GB). Con SQLite più vecchio (prima della 3.43)
l'indice non è contentless e occupa circa quanto il testo; `CALIBRE_MCP_STEMMING=1` raddoppia circa l'indice.

**Stime, non misurate dal benchmark** (scalano i valori documentati per l'indice semantico):

| Libreria | Passaggi (circa 700 per libro) | RAM per i vettori (circa 384 byte ciascuno) | Indice su disco (circa 0,6 MB per libro) | Prima costruzione semantica (1–2 h ogni 1.000 libri) |
|---|---|---|---|---|
| 500 libri | 350.000 | ~134 MB | ~300 MB | 0,5–1 h |
| 1.000 libri | 700.000 | ~270 MB | ~600 MB | 1–2 h |
| 3.000 libri | 2.100.000 | ~800 MB | ~1,8 GB | 3–6 h |

La costruzione usa di default metà dei core della CPU (`CALIBRE_MCP_EMBED_THREADS`), è incrementale e riprendibile, e le
costruzioni successive elaborano solo libri nuovi o modificati. Un libro è limitato a 1.500 passaggi (`CALIBRE_MCP_EMBED_MAX_CHUNKS`).

- **Modello di embedding:** circa 220 MB scaricati una volta, vettori a 384 dimensioni, gira sulla CPU.
- **OCR:** circa 1–3 s per pagina su CPU, quindi una scansione di 300 pagine richiede circa 5–15 minuti. L'OCR gira solo nel comando batch, mai dentro una richiesta della chat.
- **Disco in totale:** la cartella sidecar contiene l'indice full-text, gli indici opzionali semantico e delle figure, il modello e i file di lingua dell'OCR; cancellarla è sempre sicuro.

## Cosa influisce sulle prestazioni

| Impostazione | Default | Effetto |
|---|---|---|
| `CALIBRE_MCP_EMBED_THREADS` | metà dei core della CPU | più thread costruiscono più in fretta l'indice semantico e tengono il PC più impegnato |
| `CALIBRE_MCP_EMBED_MAX_CHUNKS` / `CALIBRE_MCP_EMBED_CHUNK` | 1.500 / 700 caratteri | meno passaggi, o più lunghi, danno un indice più piccolo e veloce; cambiare la dimensione richiede `--build-embeddings --rebuild` |
| `CALIBRE_MCP_THROTTLE_MS` | 5 ms | pausa per documento durante la sincronizzazione in background, per non appesantire il PC (`--sync` non ne ha) |
| `CALIBRE_MCP_SYNC_INTERVAL` | 600 s | ogni quanto gira la sincronizzazione in background; `0` = solo all'avvio |
| `CALIBRE_MCP_STEMMING` | 0 | `1` aggiunge un indice con stemming: circa il doppio del disco e una prima sincronizzazione più lunga |
| `CALIBRE_MCP_MAX_CHARS` | 12.000 | limite per chiamata di lettura: valori più bassi costano meno token al modello |
| `CALIBRE_MCP_OCR_DPI` / `CALIBRE_MCP_OCR_PAGE_TIMEOUT` | 300 / 180 s | risoluzione dei render delle pagine per l'OCR e limite di tempo per pagina |
| `CALIBRE_MCP_CONVERT_TIMEOUT` | 180 s | limite di tempo di una esecuzione di `ebook-convert` |

Oltre alle impostazioni: l'**archiviazione** (un SSD è molto meglio di una condivisione di rete o di una cartella
OneDrive, che aggiunge anche latenza di download), le **versioni di Python e SQLite** (3.12+ e SQLite 3.43+ danno
l'indice compatto), il **backend PDF** (`pymupdf` è più veloce di `pypdf`) e il **mix di formati** (i libri LIT, MOBI e
AZW3 richiedono il convertitore di Calibre la prima volta che vengono letti). Tutte le impostazioni sono descritte in
[Variabili d'ambiente](tweaking.md#variabili-dambiente).

## Misurala tu

Esegui il benchmark (richiede numpy, che viene installato con i requisiti semantici, e circa 1 GB di disco libero; crea la
sua libreria in una cartella temporanea e la rimuove alla fine):

```powershell
.venv\Scripts\python.exe tests\bench_synthetic.py                       # l'esecuzione documentata: 1.500 libri, ~525 MB
.venv\Scripts\python.exe tests\bench_synthetic.py --books 300 --runs 10 # più rapido
.venv\Scripts\python.exe tests\bench_synthetic.py --semantic-books 100 --json results.json
```

| Opzione | Default | Significato |
|---|---|---|
| `--books` | 1500 | numero di libri sintetici |
| `--avg-kb` | 296 | dimensione media del testo per libro in KB (1.500 libri ≈ 525 MB) |
| `--runs` | 30 | chiamate misurate per operazione |
| `--semantic-books` | 0 | costruisce anche l'indice semantico per questo numero di libri (backend offline `hash`) |
| `--json FILE` | | scrive i risultati in JSON |
| `--dir`, `--keep`, `--seed` | temp, off, 7 | cartella di lavoro, conserva la libreria alla fine, seme casuale |

Per cronometrare la **tua** libreria, chiama i tool come fa il benchmark (imposta prima `CALIBRE_LIBRARY`):

```python
import sys, time
sys.argv = ["x"]; sys.path.insert(0, r"C:\Tools\mcp-calibre")
import calibre_mcp as m
m.set_libraries([m.detect_library()], m.default_data_dir())
t = time.perf_counter(); m.calibre_search_fulltext(query="firewall"); print(round((time.perf_counter() - t) * 1000, 1), "ms")
```

Per i lavori lunghi, `--sync` riporta la propria durata, `--build-embeddings` stampa l'avanzamento libro per libro, e
`--embeddings-report` mostra cosa contiene l'indice semantico. La [console](tweaking.md#console-gestione-grafica) esegue e cronometra questi
lavori dalla scheda Maintenance.
