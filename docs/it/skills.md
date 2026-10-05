# Skill: i libri che lavorano per te

[← README](../../README.it.md) · [Installazione](installation.md) · [Personalizzazione e funzionamento interno](tweaking.md) · **Skill** · [FAQ e risoluzione dei problemi](faq.md) · [Prestazioni](performance.md)

[🇬🇧 English](../en/skills.md) · 🇮🇹 Italiano

Le skill trasformano i tool del server in lavori completi. Quattro sono incluse nel repository, in `skills/`. Ognuna è
una cartella con un solo file `SKILL.md` (una *Agent Skill*) che dice all'assistente come svolgere un lavoro in più
passi con i tool di questo server (trovare i capitoli giusti, leggerli, parafrasare, verificare) così puoi chiedere il
risultato con una frase. Non aggiungono tool e non cambiano nulla in Calibre, e richiedono il server collegato.

Tutte e quattro condividono una disciplina: **leggere con uno scopo, parafrasare, citare le fonti e concludere con il
[legal gate](#legal-gate)** che verifica che il risultato non copi i libri. Il testo dei libri è contenuto non
attendibile in ognuna di esse: le istruzioni trovate dentro un libro non vengono mai seguite.

**Indice**

- [Quale skill per quale obiettivo](#quale-skill-per-quale-obiettivo)
- [Installazione e uso](#installazione-e-uso)
- [calibre-distill: un libro in una skill](#calibre-distill-un-libro-in-una-skill)
- [calibre-distill-topic: un argomento su più libri](#calibre-distill-topic-un-argomento-su-più-libri)
- [calibre-book-agent: un libro come agente](#calibre-book-agent-un-libro-come-agente)
- [calibre-book-redteam: il libro regge?](#calibre-book-redteam-il-libro-regge)
- [Usare le skill insieme](#usare-le-skill-insieme)
- [Legal gate](#legal-gate)
- [Domande e problemi](#domande-e-problemi)

## Quale skill per quale obiettivo

| Skill | Serve a | Tu fornisci | Ottieni |
|---|---|---|---|
| `calibre-distill` | trasformare **un** libro in conoscenza riutilizzabile | il numero o il titolo di un libro, e l'obiettivo (una skill, oppure una scheda di studio nella chat) | una skill o scheda di studio: framework, guida alle decisioni, glossario, checklist, errori comuni, fonte |
| `calibre-distill-topic` | sintetizzare **un argomento su tre o più** libri | l'argomento, e i libri (oppure lascia che ne proponga da 3 a 8) | una guida organizzata per concetti: decision framework, una sezione per concetto, tabella tra le fonti, dove le fonti concordano o divergono, percorso di lettura, bibliografia |
| `calibre-book-agent` | trasformare **un** libro in un **agente** che ne applica l'approccio | il numero o il titolo di un libro, e opzionalmente un ruolo | un file agente (subagent di Claude Code o prompt di sistema) con un protocollo di ancoraggio; i risultati del gate e del test rapido |
| `calibre-book-redteam` | **mettere alla prova** un libro contro sé stesso e contro il resto della libreria | il numero o il titolo di un libro, opzionalmente un focus e la parte di libreria da usare | un report: affermazioni centrali, una valutazione per affermazione, la migliore difesa del libro, le fonti contrarie, cosa leggere dopo |

**Come scegliere**

- Vuoi *tenere ciò che un libro insegna* in una forma che il tuo assistente possa applicare: `calibre-distill`.
- Vuoi *confrontare ciò che dicono più libri* su un tema: `calibre-distill-topic`.
- Vuoi un assistente che *ragioni con un libro preciso*, da solo o contro un altro libro:
  `calibre-book-agent` (vedi [Libro contro libro](#libro-contro-libro-ricetta-passo-per-passo)).
- Vuoi sapere *se ci si può fidare di un libro*, o da quale di due libri costruire un agente:
  `calibre-book-redteam`.

## Installazione e uso

**Installazione**

| Client | Come |
|---|---|
| Claude Code | copia le cartelle delle skill da `skills/` in `~/.claude/skills/` |
| claude.ai e Claude Desktop | comprimi la cartella della skill in zip e caricala in Impostazioni → Capabilities → Skills |

Installa le skill che vuoi; sono indipendenti. Poi chiedi semplicemente, con parole tue, oppure nomina la skill ("usa
calibre-distill sul libro 1168"). Avvia una nuova conversazione dopo l'installazione.

**Di cosa hanno bisogno le skill**

- **Il server collegato** e funzionante ([Verifica che funzioni](installation.md#verifica-che-funzioni)): le skill usano i suoi tool.
- **Il testo del libro.** Un PDF scansionato senza livello di testo va prima sottoposto a OCR
  (`calibre_mcp.py --extract-missing --books <id>`); `calibre_library_status` mostra la copertura.
- **L'indice semantico dei libri coinvolti**, fortemente consigliato per `calibre-book-agent` e
  `calibre-book-redteam` (e utile per le altre due): costruiscilo con `calibre_mcp.py --build-embeddings --books
  <ids>`. Senza, l'assistente ripiega sulla ricerca per parole esatte e trova i passaggi in modo meno affidabile; il
  report del red-team lo dice quando il suo controllo è più debole. Vedi [Ricerca semantica](tweaking.md#funzioni-opzionali).

**Cosa aspettarsi.** Sono lavori lunghi: l'assistente legge capitoli, cerca e scrive, in decine di chiamate ai tool.
Ogni chiamata di lettura è limitata a `CALIBRE_MCP_MAX_CHARS` caratteri (12.000 di default) e paginata. Metti in conto
minuti, non secondi, e chiedi una passata rapida (meno capitoli o affermazioni) quando ti serve solo una prima impressione.

## calibre-distill: un libro in una skill

**Cosa fa.** Legge un libro capitolo per capitolo e lo trasforma in qualcosa di riutilizzabile senza riprodurlo: una
struttura di idee scritta con parole proprie dell'assistente, organizzata per concetti e non secondo l'ordine dei
capitoli del libro.

**Come chiederla**

> "Distilla il libro 1168 in una skill per responsabili di ingegneria."
> "Fammi una scheda di studio di *<titolo>*, a livello di professionista."

**Cosa succede**

1. Identifica il libro (un numero, o un titolo che cerca e ti chiede di confermare) e chiede l'obiettivo se non è
   chiaro: una skill per Claude (un `SKILL.md` con eventuali file di riferimento) oppure una scheda di studio nella chat.
2. Si orienta con i metadati del libro e la mappa dei capitoli, e salta la parte iniziale e finale.
3. Pianifica quali capitoli portano le idee che servono all'obiettivo; non ricalca l'indice.
4. Legge quei capitoli con uno scopo, individuando concetti specifici con la ricerca dentro il libro, e prende appunti
   subito in forma di parafrasi, tenendo solo un breve elenco di citazioni che valgono la pena (ciascuna sotto le 25 parole).
5. Facoltativamente guarda le figure del libro e descrive a parole l'idea di un diagramma.
6. Scrive il risultato, poi esegue il [legal gate](#legal-gate) e corregge ogni errore.

**Cosa ottieni.** Una skill o scheda con queste sezioni: *When to use*, *Core frameworks and mental models*,
*Decision guide* (se X allora Y, e i compromessi), *Glossary*, *Cheatsheet / checklists*, *Pitfalls and
counter-examples* e *Source* (titolo, autori, ISBN e i capitoli da cui attinge ogni sezione), più l'esito del gate.

**Consigli.** Di' chi è il destinatario e quanto andare in profondità (cheat sheet o guida di studio). Se vuoi la skill
installata, salvala nella tua cartella delle skill come descritto in [Installazione e uso](#installazione-e-uso). Una
distillazione è per costruzione una frazione del libro: usala per applicare il libro, e torna al libro per il dettaglio.

**Limiti.** Nessun riassunto capitolo per capitolo, nessuna tabella, listato di codice o esercizio riprodotto; gli
esempi sono dell'assistente. Se un capitolo necessario non si può leggere (nessun testo, PDF scansionato) lo dice
invece di tirare a indovinare.

## calibre-distill-topic: un argomento su più libri

**Cosa fa.** Costruisce conoscenza organizzata per **concetti**, non per libro, da tre o più libri su un tema. Il valore sta
nel confrontare e integrare le fonti; non cuce mai insieme riassunti di libri.

**Come chiederla**

> "Sintetizza l'affidabilità degli agenti da 1164, 1168 e 1162."
> "Cosa dicono i miei libri sulla risposta agli incidenti? Scegli quelli rilevanti e costruisci una guida."

**Cosa succede**

1. Fissa con precisione il tema ("affidabilità degli agenti di programmazione", non "AI") e i libri: i tuoi, oppure da 3
   a 8 che trova con la ricerca per significato (con la traduzione di una richiesta in italiano), la ricerca per parole
   esatte e i metadati, e che ti propone con una riga ciascuno perché tu confermi.
2. Mappa ogni libro: metadati, mappa dei capitoli e i passaggi che trattano il tema.
3. Legge quei passaggi e registra le affermazioni di ogni fonte come punti parafrasati con riferimenti ai capitoli.
4. Costruisce la mappa dei concetti: per ciascuno, dove i libri concordano, dove si completano (angolazioni diverse) e
   dove divergono, e perché (epoca, contesto, presupposti).
5. Scrive la guida, esegue il [legal gate](#legal-gate) su tutto con tutte le fonti e corregge gli errori.

**Cosa ottieni.** *Ambito e quando usare la guida*; un *decision framework* per il tema; *una sezione per concetto* con
le sue fonti; una *tabella tra le fonti* (concetto per libro); *dove le fonti divergono o si completano*; un *percorso
di lettura* (quale libro per cosa, in che ordine); una *bibliografia* con titolo, autori, anno, ISBN e id nella libreria.

**Consigli.** Fornisci tre o più libri che coprano davvero il tema. Se un concetto poggia su una sola fonte, la guida lo
dice. Per decidere quale libro dell'insieme meriti fiducia, esegui [`calibre-book-redteam`](#calibre-book-redteam-il-libro-regge) su di esso.

**Limiti.** Se la libreria copre poco il tema (risultati deboli o `low_confidence`) te lo dice invece di riempire la
guida. Ogni affermazione è attribuita alla sua fonte, e le inferenze dell'assistente sono segnalate come tali.

## calibre-book-agent: un libro come agente

**Cosa fa.** Trasforma un libro in un **agente** che applica il modo di pensare del libro a un problema e **verifica il libro
prima di parlare a suo nome**. Non è l'autore e non lo imita mai: è "l'approccio di *<titolo>*", con i suoi limiti
dichiarati in anticipo. Il risultato è un profilo compatto più un protocollo, non una copia condensata del libro:
l'agente recupera i dettagli dalla libreria quando gli servono.

**Come chiederla**

> "Crea un agente dal libro 1168."
> "Costruisci un agente da *<titolo>* con il ruolo dello scettico, come subagent di Claude Code."

**Cosa succede**

1. Controlla che il libro abbia testo (altrimenti si ferma e ti dice come rimediare) e stabilisce che tipo di libro è: un
   libro di *metodo* dà un coach, un libro di *tesi* un sostenitore, un libro di *consultazione* un aiuto per cercare
   informazioni. Una pura narrativa dà un agente scarno; lo dice e suggerisce invece `calibre-distill`.
2. Legge l'introduzione, la conclusione e i capitoli che portano il metodo, individuando i passaggi che guidano le
   decisioni con la ricerca dentro il libro.
3. Costruisce il profilo con parole proprie: **tesi**, **principi**, **euristiche di decisione** ("se X, allora Y,
   perché..."), **vocabolario**, **prime domande**, **metodo** (se il libro ha un processo) e **punti ciechi e limiti**.
4. Scrive il file dell'agente, esegue su di esso il [legal gate](#legal-gate) e un **test rapido** con tre domande
   (qui sotto).

**Cosa ottieni.** La definizione di un agente: un file subagent di Claude Code (default) oppure un prompt di sistema per
un altro client, più l'esito del gate e quello del test rapido. Dentro il file:

- **Protocollo di ancoraggio.** Prima di presentare qualcosa come posizione del libro, l'agente la verifica con il
  server (ricerca dentro il libro, poi legge il passaggio) e cita il capitolo. Etichetta ogni posizione come **grounded**
  (trovata, con capitolo), **inferred** (un'estensione del libro, ragionamento mostrato) oppure **outside the book**
  ("il libro non ne parla"; ogni ragionamento generale è etichettato come proprio). Non inventa mai una citazione e
  usa al massimo una breve citazione per risposta.
- **Formato delle risposte.** Raccomandazione, perché (la base nel libro, con etichette), rischi e quando l'approccio
  fallisce, cosa verificare dopo.
- **Regole dello scambio** per dibattere o collaborare con l'agente di un altro libro (vedi [Libro contro libro](#libro-contro-libro-ricetta-passo-per-passo)).

**Il test rapido.** Tre domande scritte a partire dal profilo: una a cui il libro risponde esplicitamente (**IN**:
aspettati *grounded* con un capitolo che lo dice davvero), una che il libro suggerisce soltanto (**EDGE**: aspettati
*inferred*, con il passaggio del ragionamento) e una fuori dal suo ambito (**OUT**: aspettati "il libro non ne parla"
e nessuna posizione inventata). Se il client può avviare il subagent, il test usa l'agente vero; altrimenti
l'assistente segue il file alla lettera e riporta che il test è stato simulato.

**Installare l'agente.** Claude Code: salva il file come `.claude/agents/book-<slug>.md` nel tuo progetto (o nella tua
cartella home per tutti i progetti). Altri client: incollalo come prompt di sistema. Il file ha una riga `tools:`
facoltativa e commentata per limitare l'agente ai tool di sola lettura sul libro; Claude Code chiama i tool MCP
`mcp__<server>__<tool>`, dove `<server>` è il nome con cui hai registrato il server.

**Consigli.** Dai un ruolo per accentuare il contrasto in un dibattito ("l'implementatore pragmatico", "lo scettico").
Esegui prima [`calibre-book-redteam`](#calibre-book-redteam-il-libro-regge) se stai scegliendo tra due libri.

**Limiti.** Un libro per agente (per un argomento su più libri usa `calibre-distill-topic`). Non mette mai parole in
bocca all'autore e non afferma nulla sulle opinioni dell'autore oltre il libro. Dice quando un libro è una base povera
per un agente (narrativa, molto breve, datato) invece di riempire il profilo.

## calibre-book-redteam: il libro regge?

**Cosa fa.** Scopre quali affermazioni centrali di un libro sopravvivono al confronto con il resto della tua libreria. Il
risultato è un report equo, non una stroncatura: ogni affermazione è prima enunciata nella sua forma più forte, poi
confrontata con ciò che dice la libreria.

**Il limite onesto.** Le prove sono ciò che c'è nella *tua* libreria. Non trovare contraddizioni non è una prova, e un
libro che non possiedi non può obiettare. Ogni valutazione dice in quale delle due situazioni ci si trova, e il report
non pretende mai di aver controllato tutta la letteratura.

**Come chiederla**

> "Il libro 1168 regge? Verifica le sue affermazioni contro la mia libreria."
> "Metti alla prova *<titolo>*, concentrandoti sul capitolo 4, usando solo i miei libri di management."

**Cosa succede**

1. Legge i metadati del libro (anno, editore) e la mappa dei capitoli; l'età e il tipo di libro cambiano il modo di giudicarlo.
2. Estrae da 3 a 10 **affermazioni centrali** dall'introduzione, dalla conclusione e dai capitoli che portano la tesi,
   ciascuna come una frase parafrasata con il suo capitolo, classificata come empirica, causale, prescrittiva o
   definitoria, e annota le prove che il libro offre (dati, esempio svolto, aneddoto, autorità o nessuna).
3. Controlla il libro **contro sé stesso**: la stessa affermazione detta in modo diverso in due punti, termini il cui
   significato cambia, conclusioni che superano le prove, consigli validi solo a condizioni che il libro non
   dichiara, esempi presi solo dai successi.
4. Controlla ogni affermazione **contro la libreria**: ricerca per significato con formulazioni che la sosterrebbero e
   che la contraddirebbero (e traduzioni quando la libreria è mista), ricerca per termini esatti, libri simili. Ignora
   il libro stesso e i risultati deboli `low_confidence`, apre i passaggi migliori per giudicarli nel contesto e pesa
   **indipendenza e data**: più libri dello stesso autore, o che si citano a vicenda, contano come una sola voce, e un
   libro più vecchio non può confutare uno più recente su un punto cambiato.
5. Per ogni affermazione non chiaramente sostenuta scrive prima la migliore difesa del libro, poi le prove contrarie,
   poi la valutazione.
6. Scrive il report ed esegue su di esso il [legal gate](#legal-gate) con tutte le fonti citate.

**Le valutazioni**

| Valutazione | Significato |
|---|---|
| Supported | fonti indipendenti nella libreria concordano |
| Qualified | le fonti concordano in parte, o solo a condizioni che il libro non dichiara |
| Contested | fonti di peso comparabile non sono d'accordo |
| Contradicted | fonti della libreria con prove pari o migliori la contraddicono |
| Unverifiable here | la libreria non ha una copertura pertinente (né a favore né contro) |

Ogni valutazione indica quanto sono solide le sue prove: quante fonti, quanto indipendenti, quanto direttamente
trattano l'affermazione.

**Cosa ottieni.** Un report con: il **verdetto** (su cosa fare affidamento, cosa verificare altrove, cosa trattare con
cautela); **ambito e limiti** del controllo; la **tabella delle affermazioni**; un blocco per ogni affermazione
contestata o contraddetta (la difesa del libro, le fonti contrarie con titolo, id nella libreria e capitolo, la tua
valutazione); i **problemi interni**; **ciò che il libro fa bene**; i suoi **punti ciechi**; **cosa leggere dopo**; e le
**fonti**.

**Consigli.** Usalo prima di costruire un agente o una skill su un libro, e per scegliere lo sparring partner di un
dibattito. Limita le prove con una query di Calibre (un tag, una serie, una libreria virtuale) quando la libreria è ampia.

**Limiti.** Solo prove della libreria. Se l'indice semantico non copre i libri pertinenti, lo dice e ripiega sulla
ricerca per parole esatte, precisando che il controllo è più debole. Non fabbrica opposizione: se la libreria sostiene
il libro lo dice, e se non ha nulla da dire l'affermazione è valutata *Unverifiable here*.

## Usare le skill insieme

### Il metodo di un libro come skill

Scegli un libro di metodo (management, negoziazione, gestione dei progetti, sicurezza...) ed esegui `calibre-distill` su di
esso. La skill che scrive contiene il metodo nelle sezioni *When to use*, *Core frameworks*, *Decision guide* e
*Cheatsheet / checklists*. Installala, poi chiedi al tuo assistente di applicarla a una situazione reale:

> "Usa il metodo del libro 1168 per pianificare questa riorganizzazione."

La skill è una parafrasi dell'assistente, verificata dal legal gate, quindi puoi tenerla e modificarla; il libro resta
nella tua libreria, e l'assistente può ancora cercarlo e leggerlo tramite il server per verificare un punto.

### Libro contro libro: ricetta passo per passo

Due libri sullo stesso problema, ciascuno incarnato da un agente, ne discutono o costruiscono insieme un piano.

1. **Scegli il problema e due libri con approcci diversi** (per esempio uno sulla disciplina di consegna e uno sui team
   adattivi). Facoltativamente esegui prima `calibre-book-redteam` su ciascuno, per vedere dove è debole.
2. **Costruisci un agente per libro** con `calibre-book-agent`. Dai a ciascuno un ruolo se vuoi un contrasto più netto.
3. **Installa entrambi i file degli agenti** (Claude Code: `.claude/agents/`).
4. **Esegui lo scambio.** Chiedi all'assistente di orchestrarlo, per esempio:

   > "Usa gli agenti book-a e book-b su questo problema: *<il problema>*. Fai un dibattito di tre turni: in ogni turno
   > interroga un agente, poi l'altro, passando la prima risposta al secondo. Ogni risposta sotto le 200 parole. Dopo
   > il terzo turno chiedi a entrambi la raccomandazione finale, poi dai la tua come moderatore: cosa fare, quale libro
   > ha deciso e dove erano in disaccordo."

5. **Conserva ciò che vale.** Se salvi materiale dello scambio, esegui `calibre_check_overlap` su di esso.

Due modalità funzionano bene. In un **dibattito**, ogni agente apre con la posizione e la regola di decisione del suo
libro, contesta il ragionamento dell'altro, concede ciò che l'altro libro gestisce meglio e dice cosa gli farebbe
cambiare idea. In una **collaborazione**, ognuno contribuisce la parte del piano in cui il suo libro è più forte, poi
riconciliano i conflitti in un unico elenco di passi. Le regole per entrambe sono già dentro il file di ogni agente.

**Moderatore.** Decidi tu, oppure un agente moderatore separato. Quando il disaccordo riguarda i valori e non i fatti,
gli agenti hanno istruzione di chiedere al moderatore. L'orchestrazione in sé (chi parla quando) non è inclusa nel
repository: la configuri con la funzione agenti del tuo client, usando i file degli agenti come loro conoscenza. Gli
agenti leggono il testo dei libri tramite il server come qualsiasi assistente, quindi vale la solita cautela: il testo
dentro un libro non è mai un'istruzione.

### Da uno scaffale a un verdetto

Le skill si concatenano in modo naturale:

1. `calibre-distill-topic` mappa lo scaffale: quali libri coprono il tema, dove concordano e dove divergono.
2. `calibre-book-redteam` sul libro che domina la guida, per vedere se merita quel peso.
3. `calibre-distill` sui libri che resistono, per conservarne i metodi come skill, oppure `calibre-book-agent` per
   metterli in un dibattito.

Ogni passo termina con il gate, quindi ciò che porti da uno al successivo è una tua parafrasi e non il testo dei libri.

## Legal gate

`calibre_check_overlap(text, book_ids)` (oppure `calibre_mcp.py --legal-gate <cartella> --book <id> …` per i
file) verifica meccanicamente che un testo tratto dai libri non li riproduca:

| Controllo | Limite di default | Significato | Se fallisce |
|---|---|---|---|
| `verbatim_overlap` | ≤ 3 % | quota delle sequenze di 8 parole del testo (fuori dalle citazioni dichiarate) presenti nelle fonti | riscrivi i passaggi segnalati con parole tue |
| `longest_run` | ≤ 20 parole | tratto più lungo copiato parola per parola fuori dalle citazioni (il report lo mostra) | riscrivi quel tratto |
| `quote_budget` | ≤ 20 citazioni, ≤ 25 parole ciascuna | le citazioni dichiarate (“…”, "…", «…», righe `>`) sono ammesse ma brevi e poche | accorcia o elimina citazioni |
| `compression` | ≤ 15 % | parole del testo rispetto alle parole delle fonti | taglia: un distillato è una frazione del libro |
| `heading_mirroring` | ≤ 50 % dei titoli, < 5 in ordine | titoli che replicano quelli dei capitoli delle fonti o la loro sequenza | riorganizza per concetti |
| `attribution` | ogni fonte | ogni libro citato per titolo, cognome di un autore o ISBN | aggiungi una sezione Fonte / Bibliografia |

La CLI termina con 0 se tutto passa e con 1 altrimenti, quindi si può usare in uno script. Un PASS è una prova
meccanica di trasformazione, **non un parere legale**.

## Domande e problemi

### L'assistente non usa la skill

Controlla che la skill sia installata dove il tuo client la legge ([Installazione e uso](#installazione-e-uso)) e avvia una nuova conversazione. Nomina la skill nella richiesta ("usa calibre-distill sul libro 1168"). Il server deve essere collegato: le skill si limitano a guidare i suoi tool.

### Dice che il libro non ha testo

Il libro è un PDF scansionato oppure Calibre non ne ha ancora estratto il testo. `calibre_library_status` mostra la copertura. Esegui `calibre_mcp.py --extract-missing --books <id>` (fa l'OCR dei PDF scansionati) e poi `calibre_mcp.py --build-embeddings --books <id>`. Vedi [OCR per i PDF scansionati](tweaking.md#ocr-per-i-pdf-scansionati).

### Le ricerche dentro il libro non trovano nulla, o tutto è `low_confidence`

L'indice semantico probabilmente non copre ancora quel libro, oppure l'argomento non c'è. Verifica con `calibre_mcp.py --embeddings-report` e costruiscilo con `--build-embeddings --books <ids>`. Vedi [Ricerca semantica](tweaking.md#funzioni-opzionali) e le [FAQ](faq.md#problemi-durante-luso).

### Il legal gate fallisce

Il report indica il controllo fallito; la tabella in [Legal gate](#legal-gate) dice come correggere ciascuno (riscrivere un tratto copiato, accorciare le citazioni, tagliare quando `compression` fallisce, raggruppare diversamente i titoli che ricalcano il libro, aggiungere la fonte). L'assistente corregge e lo riesegue finché non passa.

### L'agente inventa ciò che dice il libro

Esegui il test rapido (la domanda OUT deve dare "il libro non ne parla"). Assicurati che l'agente possa chiamare i tool sul libro: se limiti `tools:` nel file, includi i tool sul libro, che Claude Code chiama `mcp__<server>__calibre_search_semantic` e così via. Ogni posizione senza capitolo deve essere etichettata *inferred* o *outside the book*.

### Il red-team valuta quasi tutto "Unverifiable here"

La tua libreria ha poco sull'argomento. Allarga la parte di libreria usata come prova (o togli il `query_filter`), aggiungi libri pertinenti, oppure accetta la risposta: è un'informazione, non un fallimento.

### Posso usare le skill con ChatGPT o Codex?

Le strade documentate sono Claude Code, Claude Desktop e claude.ai, che supportano le Agent Skill. Un `SKILL.md` è Markdown semplice, quindi un altro client potrebbe permetterti di incollarlo come istruzioni, ma qui non è stato provato. Il server e i suoi tool funzionano in ogni client.

### Ciò che producono le skill si può condividere senza rischi?

Il gate è un'evidenza meccanica che il testo è una trasformazione e non una copia; non è una consulenza legale. Il risultato è una parafrasi dell'assistente con le fonti citate, ma le norme sul diritto d'autore cambiano da paese a paese: verificale prima di pubblicare.
