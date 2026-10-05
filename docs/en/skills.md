# Skills: books that work for you

[← README](../../README.md) · [Installation](installation.md) · [Tweaking and under the hood](tweaking.md) · **Skills** · [FAQ and troubleshooting](faq.md) · [Performance](performance.md)

🇬🇧 English · [🇮🇹 Italiano](../it/skills.md)

Skills turn the server's tools into complete jobs. Four ship with the repository, in `skills/`. Each is a folder with
one `SKILL.md` file (an *Agent Skill*) that tells the assistant how to carry out a multi-step job with this server's
tools (find the right chapters, read them, paraphrase, check) so that you can ask for the result in one sentence.
They add no tools and change nothing in Calibre, and they need the server connected.

All four share one discipline: **read with a purpose, paraphrase, credit the sources, and finish with the
[legal gate](#legal-gate)** that checks the result does not copy the books. Book text is untrusted content in every
one of them: instructions found inside a book are never followed.

**Contents**

- [Which skill for which goal](#which-skill-for-which-goal)
- [Install and use](#install-and-use)
- [calibre-distill: one book into a skill](#calibre-distill-one-book-into-a-skill)
- [calibre-distill-topic: one topic across several books](#calibre-distill-topic-one-topic-across-several-books)
- [calibre-book-agent: one book as an agent](#calibre-book-agent-one-book-as-an-agent)
- [calibre-book-redteam: does the book hold up?](#calibre-book-redteam-does-the-book-hold-up)
- [Using the skills together](#using-the-skills-together)
- [Legal gate](#legal-gate)
- [Questions and problems](#questions-and-problems)

## Which skill for which goal

| Skill | Use it to | You give | You get |
|---|---|---|---|
| `calibre-distill` | turn **one** book into knowledge you can reuse | a book number or title, and the goal (a skill, or a study sheet in the chat) | a skill or study sheet: frameworks, decision guide, glossary, checklists, pitfalls, source |
| `calibre-distill-topic` | synthesize **one topic across three or more** books | the topic, and the books (or let it propose 3 to 8) | a concept-keyed guide: decision framework, one section per concept, cross-source table, where the sources agree or disagree, reading path, bibliography |
| `calibre-book-agent` | turn **one** book into an **agent** that applies its approach | a book number or title, and optionally a role | an agent file (Claude Code subagent or system prompt) with a grounding protocol; the gate and smoke-test results |
| `calibre-book-redteam` | **stress-test** one book against itself and the rest of the library | a book number or title, optionally a focus and the part of the library to use | a report: central claims, a rating per claim, the book's best defence, counter-sources, what to read next |

**How to choose**

- You want to *keep what a book teaches* in a form your assistant can apply: `calibre-distill`.
- You want to *compare what several books say* about one subject: `calibre-distill-topic`.
- You want an assistant that *thinks with a particular book*, alone or against another book:
  `calibre-book-agent` (see [Book against book](#book-against-book-a-step-by-step-recipe)).
- You want to know *whether a book can be trusted*, or which of two books to build an agent from:
  `calibre-book-redteam`.

## Install and use

**Install**

| Client | How |
|---|---|
| Claude Code | copy the skill folder(s) from `skills/` into `~/.claude/skills/` |
| claude.ai and Claude Desktop | zip the skill folder and upload it in Settings → Capabilities → Skills |

Install the skills you want; they are independent. Then just ask, in your own words, or name the skill ("use
calibre-distill on book 1168"). Start a new conversation after installing.

**What the skills need**

- **The server connected** and working ([Check that it works](installation.md#check-that-it-works)): skills use its tools.
- **Text for the book.** A scanned PDF with no text layer must be OCRed first
  (`calibre_mcp.py --extract-missing --books <id>`); `calibre_library_status` shows the coverage.
- **The semantic index for the books involved**, strongly recommended for `calibre-book-agent` and
  `calibre-book-redteam` (and useful for the other two): build it with `calibre_mcp.py --build-embeddings --books
  <ids>`. Without it the assistant falls back to exact-word search and finds passages less reliably; the red-team
  report says so when its check is weaker. See [Semantic search](tweaking.md#optional-features).

**What to expect.** These are long jobs: the assistant reads chapters, searches and writes, in dozens of tool calls.
Each read call is capped at `CALIBRE_MCP_MAX_CHARS` characters (12,000 by default) and paged. Plan for minutes, not
seconds, and ask for a quick pass (fewer chapters or claims) when you only need a first impression.

## calibre-distill: one book into a skill

**What it does.** Reads one book chapter by chapter and turns it into something you can reuse without reproducing it:
a structure of ideas written in the assistant's own words, organized by concept and not by the book's chapter order.

**Ask for it**

> "Distill book 1168 into a skill for engineering managers."
> "Make me a study sheet of *<title>*, practitioner level."

**What happens**

1. It identifies the book (a number, or a title it searches and asks you to confirm) and asks for the goal if unclear:
   a Claude skill (a `SKILL.md` with optional reference files) or a study sheet in the chat.
2. It orients itself with the book's metadata and chapter map, and skips front and back matter.
3. It plans which chapters carry the ideas the goal needs; it does not mirror the table of contents.
4. It reads those chapters with purpose, locating specific concepts with search inside the book, and takes notes as
   paraphrase at once, keeping only a short list of quotations worth keeping (each under 25 words).
5. Optionally it looks at the book's figures and describes the idea of a diagram in words.
6. It writes the result, then runs the [legal gate](#legal-gate) and fixes every failure.

**What you get.** A skill or sheet with these sections: *When to use*, *Core frameworks and mental models*, *Decision
guide* (if X then Y, and the trade-offs), *Glossary*, *Cheatsheet / checklists*, *Pitfalls and counter-examples* and
*Source* (title, authors, ISBN and the chapters each section draws on), plus the gate result.

**Tips.** Say who the audience is and how deep to go (cheat sheet or study guide). If you want the skill installed,
save it into your skills folder as described in [Install and use](#install-and-use). A distill is a fraction of the book
by design: use it to apply the book, and go back to the book for the detail.

**Limits.** No chapter-by-chapter summary, no reproduced tables, code listings or exercises; examples are the
assistant's own. If a needed chapter cannot be read (no text, scanned PDF) it says so instead of guessing.

## calibre-distill-topic: one topic across several books

**What it does.** Builds knowledge keyed by **concepts**, not by book, from three or more books on one subject. The value is
in comparing and integrating sources; it never stitches book summaries together.

**Ask for it**

> "Synthesize agent reliability from 1164, 1168 and 1162."
> "What do my books say about incident response? Pick the relevant ones and build a guide."

**What happens**

1. It fixes the topic precisely ("reliability of coding agents", not "AI") and the books: yours, or 3 to 8 it finds
   with meaning search (with a translation of an Italian request), exact-word search and metadata, and proposes
   with one line each for you to confirm.
2. It maps each book: metadata, chapter map, and the passages that address the topic.
3. It reads those passages and records each source's claims as paraphrased points with chapter references.
4. It builds the concept map: for each concept, where the books agree, where they complement each other (different
   angles), and where they disagree, and why (era, context, assumptions).
5. It writes the guide, runs the [legal gate](#legal-gate) on everything with all the sources, and fixes failures.

**What you get.** *Scope and when to use the guide*; a *decision framework* for the topic; *one section per concept*
with its sources; a *cross-source table* (concept by book); *where the sources disagree or complement each other*; a
*reading path* (which book for what, in which order); a *bibliography* with title, authors, year, ISBN and library id.

**Tips.** Give three or more books that really cover the topic. If a concept rests on one source, the guide says so.
To decide which book of the set deserves trust, run [`calibre-book-redteam`](#calibre-book-redteam-does-the-book-hold-up) on it.

**Limits.** If the library covers the topic weakly (weak or `low_confidence` matches) it tells you instead of padding
the guide. Every claim is attributed to its source, and the assistant's own inferences are marked as such.

## calibre-book-agent: one book as an agent

**What it does.** Turns one book into an **agent** that applies the book's way of thinking to a problem and **checks the
book before it speaks for it**. It is not the author and never imitates them: it is "the approach of *<title>*", with
its limits stated up front. The output is a compact profile plus a protocol, not a condensed copy of the book: the
agent fetches details from the library when it needs them.

**Ask for it**

> "Make an agent from book 1168."
> "Build an agent from *<title>* with the role of the sceptic, as a Claude Code subagent."

**What happens**

1. It checks the book has text (otherwise it stops and tells you how to fix it) and decides the kind of book: a
   *method* book gives a coach, an *argument* book an advocate, a *reference* book a lookup helper. A pure narrative
   gives a thin agent; it says so and suggests `calibre-distill` instead.
2. It reads the introduction, the conclusion and the chapters that carry the method, locating decision-bearing
   passages with search inside the book.
3. It builds the profile in its own words: **thesis**, **principles**, **decision heuristics** ("if X, then Y,
   because..."), **vocabulary**, **first questions**, **method** (if the book has a process) and **blind spots and
   limits**.
4. It writes the agent file, runs the [legal gate](#legal-gate) on it, and runs a **smoke test** of three questions
   (below).

**What you get.** An agent definition: a Claude Code subagent file (default) or a system prompt for another client,
plus the gate result and the smoke-test results. Inside the file:

- **Grounding protocol.** Before presenting something as the book's position, the agent checks it with the server
  (search inside the book, then reads the passage) and cites the chapter. It labels every position **grounded** (found,
  with chapter), **inferred** (an extension of the book, reasoning shown) or **outside the book** ("the book is
  silent"; any general reasoning is labelled as its own). It never invents a quotation and uses at most one short
  quotation per answer.
- **Answer format.** Recommendation, why (the book's basis, with labels), risks and when the approach fails, what to
  check next.
- **Exchange rules** for debating or collaborating with another book's agent (see [Book against book](#book-against-book-a-step-by-step-recipe)).

**The smoke test.** Three questions written from the profile: one the book answers explicitly (**IN**: expect
*grounded* with a chapter that really says it), one it only implies (**EDGE**: expect *inferred*, with the reasoning
step), and one outside its scope (**OUT**: expect "the book is silent" and no invented position). If the client can
launch the subagent, the test runs the real agent; otherwise the assistant follows the file to the letter and reports
that the test was simulated.

**Install the agent.** Claude Code: save the file as `.claude/agents/book-<slug>.md` in your project (or in your home
folder for all projects). Other clients: paste it as the system prompt. The file has an optional, commented `tools:`
line to restrict the agent to read-only book tools; Claude Code names MCP tools `mcp__<server>__<tool>`, with
`<server>` being the name you registered the server under.

**Tips.** Give a role to sharpen the contrast in a debate ("the pragmatic implementer", "the sceptic"). Run
[`calibre-book-redteam`](#calibre-book-redteam-does-the-book-hold-up) first if you are choosing between two books.

**Limits.** One book per agent (for a topic across books use `calibre-distill-topic`). It never puts words in the
author's mouth and makes no claim about the author's opinions beyond the book. It says when a book is a poor basis for
an agent (narrative, very short, dated) instead of padding the profile.

## calibre-book-redteam: does the book hold up?

**What it does.** Finds out which of a book's central claims survive contact with the rest of your library. The result is a
fair report, not a hit piece: each claim is stated at its strongest first, then compared with what the library says.

**The honest limit.** The evidence is what is in *your* library. Finding no contradiction is not proof, and a book you
do not own cannot object. Every rating says which of the two situations it is, and the report never claims to have
checked the whole literature.

**Ask for it**

> "Does book 1168 hold up? Check its claims against my library."
> "Red-team *<title>*, focusing on chapter 4, using only my management books."

**What happens**

1. It reads the book's metadata (year, publisher) and chapter map; the book's age and kind change how it is judged.
2. It extracts the 3 to 10 **central claims** from the introduction, the conclusion and the chapters that carry the
   argument, each as one paraphrased sentence with its chapter, classified as empirical, causal, prescriptive or
   definitional, and notes the evidence the book gives (data, worked example, anecdote, authority or none).
3. It checks the book **against itself**: the same claim stated differently in two places, terms whose meaning shifts,
   conclusions that outrun their evidence, advice that holds only under conditions the book never states, examples
   drawn only from successes.
4. It checks each claim **against the library**: meaning search with phrasings that would support and contradict it
   (and translations when the library is mixed), exact-term search, similar books. It ignores the book itself and
   weak `low_confidence` matches, opens the best passages to judge them in context, and weighs **independence and date**:
   several books by one author, or that cite each other, count as one voice, and an older book cannot rebut a newer
   one on a point that changed.
5. For every claim that is not plainly supported it writes the book's best defence first, then the counter-evidence,
   then the rating.
6. It writes the report and runs the [legal gate](#legal-gate) on it with every source cited.

**The ratings**

| Rating | Meaning |
|---|---|
| Supported | independent sources in the library agree |
| Qualified | sources agree in part, or only under conditions the book does not state |
| Contested | sources of comparable weight disagree |
| Contradicted | library sources with equal or better evidence contradict it |
| Unverifiable here | the library has no relevant coverage (neither for nor against) |

Each rating states how strong its evidence is: how many sources, how independent, how directly they address the claim.

**What you get.** A report with: the **verdict** (what to rely on, what to verify elsewhere, what to treat with
caution); the **scope and limits** of the check; the **claims table**; a block for each contested or contradicted
claim (the book's defence, the counter-sources with title, library id and chapter, your assessment); **internal
issues**; **what the book gets right**; its **blind spots**; **what to read next**; and the **sources**.

**Tips.** Use it before building an agent or a skill on a book, and to choose the sparring partner for a debate. Limit
the evidence with a Calibre query (a tag, a series, a virtual library) when the library is broad.

**Limits.** Library evidence only. If the semantic index does not cover the relevant books, it says so and falls back
on exact-word search, stating that the check is weaker. It does not manufacture opposition: if the library supports the
book it says so, and if it has nothing to say the claim is rated *Unverifiable here*.

## Using the skills together

### A book's method as a skill

Pick a method book (management, negotiation, project delivery, security...) and run `calibre-distill` on it. The skill it
writes holds the method in its *When to use*, *Core frameworks*, *Decision guide* and *Cheatsheet / checklists*
sections. Install it, then ask your assistant to apply it to a real situation:

> "Use the method of book 1168 to plan this reorganisation."

The skill is the assistant's own paraphrase, checked by the legal gate, so you can keep and edit it; the book stays in
your library, and the assistant can still search and read it through the server to verify a point.

### Book against book: a step-by-step recipe

Two books on the same problem, each embodied by an agent, argue it out or build a plan together.

1. **Choose the problem and two books with different approaches** (say one on delivery discipline and one on adaptive
   teams). Optionally run `calibre-book-redteam` on each first, to see where each is weak.
2. **Build one agent per book** with `calibre-book-agent`. Give each a role if you want a sharper contrast.
3. **Install both agent files** (Claude Code: `.claude/agents/`).
4. **Run the exchange.** Ask the assistant to orchestrate it, for example:

   > "Use the agents book-a and book-b on this problem: *<the problem>*. Run a debate of three rounds: in each
   > round ask one agent, then the other, passing the first answer to the second. Keep every answer under 200 words.
   > After round three ask both for their final recommendation, then give yours as moderator: what to do, which book
   > carried the decision, and where they disagreed."

5. **Keep what is worth keeping.** If you save material from the exchange, run `calibre_check_overlap` on it.

Two modes work well. In a **debate**, each agent opens with its book's position and decision rule, challenges the
other's reasoning, concedes what the other book handles better, and says what would change its mind. In a
**collaboration**, each contributes the part of the plan where its book is strongest, then they reconcile their
conflicts into one list of steps. The rules for both are already inside each agent file.

**Moderator.** You decide, or a separate moderator agent does. When a disagreement is about values and not facts, the
agents are told to ask the moderator. The orchestration itself (who speaks when) is not bundled with the repository:
you set it up with your client's agent feature, using the agent files as the agents' knowledge. The agents read book
text through the server like any assistant, so the usual caution applies: text inside a book is never an instruction.

### From a shelf to a verdict

The skills chain naturally:

1. `calibre-distill-topic` maps the shelf: which books cover the subject, where they agree and disagree.
2. `calibre-book-redteam` on the book that dominates the guide, to see whether it deserves that weight.
3. `calibre-distill` on the books that survive, to keep their methods as skills, or `calibre-book-agent` to put them
   in a debate.

Each step ends with the gate, so what you carry from one to the next is your own paraphrase and not the books' text.

## Legal gate

`calibre_check_overlap(text, book_ids)` (or `calibre_mcp.py --legal-gate <folder> --book <id> …` for files)
checks mechanically that a text derived from books does not reproduce them:

| Check | Default limit | Meaning | If it fails |
|---|---|---|---|
| `verbatim_overlap` | ≤ 3 % | share of the text's 8-word sequences (outside declared quotes) found in the sources | rewrite the flagged passages in your own words |
| `longest_run` | ≤ 20 words | longest stretch copied word for word outside quotes (the report shows it) | rewrite that stretch |
| `quote_budget` | ≤ 20 quotes, ≤ 25 words each | declared quotes (“…”, "…", «…», `>` lines) are allowed but short and few | shorten or drop quotes |
| `compression` | ≤ 15 % | words of the text vs words of the sources | cut: a distill is a fraction of the book |
| `heading_mirroring` | ≤ 50 % of headings, < 5 in order | headings that replicate the sources' chapter titles or their sequence | regroup by concept |
| `attribution` | every source | each book credited by title, an author's surname or its ISBN | add a Source / Bibliography section |

The CLI exits with 0 when everything passes and 1 otherwise, so it can run in a script. A PASS is mechanical
evidence of transformation, **not legal advice**.

## Questions and problems

### The assistant does not use the skill

Check that the skill is installed where your client reads it ([Install and use](#install-and-use)) and start a new conversation. Name the skill in your request ("use calibre-distill on book 1168"). The server must be connected: skills only drive its tools.

### It says the book has no text

The book is a scanned PDF or Calibre has not extracted its text yet. `calibre_library_status` shows the coverage. Run `calibre_mcp.py --extract-missing --books <id>` (it OCRs scanned PDFs) and then `calibre_mcp.py --build-embeddings --books <id>`. See [OCR for scanned PDFs](tweaking.md#ocr-for-scanned-pdfs).

### Searches inside the book find nothing, or everything is `low_confidence`

The semantic index probably does not cover that book yet, or the topic is not in it. Check with `calibre_mcp.py --embeddings-report` and build it with `--build-embeddings --books <ids>`. See [Semantic search](tweaking.md#optional-features) and the [FAQ](faq.md#problems-while-using-it).

### The legal gate fails

The report names the failing check; the table in [Legal gate](#legal-gate) says how to fix each one (rewrite a copied stretch, shorten quotes, cut when `compression` fails, regroup headings that mirror the book, add the source). The assistant fixes and re-runs it until it passes.

### The agent invents what the book says

Run the smoke test (the OUT question must give "the book is silent"). Make sure the agent can call the book tools: if you restrict `tools:` in the file, include the book tools, which Claude Code names `mcp__<server>__calibre_search_semantic` and so on. Every position without a chapter should be labelled *inferred* or *outside the book*.

### The red-team rates almost everything "Unverifiable here"

Your library has little on the subject. Widen the part of the library used as evidence (or drop the `query_filter`), add relevant books, or accept the answer: it is information, not a failure.

### Can I use the skills with ChatGPT or Codex?

The documented routes are Claude Code, Claude Desktop and claude.ai, which support Agent Skills. A `SKILL.md` is plain Markdown, so another client may let you paste it as instructions, but that is not tested here. The server and its tools work in every client.

### Is what the skills produce safe to share?

The gate is mechanical evidence that the text is a transformation and not a copy; it is not legal advice. The output is the assistant's own paraphrase with credited sources, but copyright rules differ by country: check them before publishing.
