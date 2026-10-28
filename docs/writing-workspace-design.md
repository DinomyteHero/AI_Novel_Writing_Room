# Writers Room: a workspace for writing fiction

Design proposal · 27 October 2026 · Product and system design. For discussion, not an implemented feature specification.

**Thesis.** A writing partner that holds the whole book in view, helps the writer make choices, and turns those choices into a manuscript the writer owns.

Take the useful interaction pattern from Cowork: give it a goal, watch the work, steer it, and review the result in the files. Make every part of that experience specific to writing: story intent, character voice, continuity, scene work, revision, and research. [Cowork product overview](https://claude.com/product/cowork)

This is an extension of the current application, not a replacement architecture. Findings below come from reading the code and tests in this repository, not from running the app end to end for this pass.

---

## 1. Product direction

**Who it is for.** Novelists and series writers, fanfiction and original fiction, short fiction as well as books. Both discovery writers and outliners. The writer may be new to craft; they should not need to learn a prompting system before they get help.

**What it promises.** *It remembers the whole book, argues about it with you, and does the paperwork.* The distinctive feature is the quality of the editorial conversation. "The scene feels flat" should produce a precise explanation, two or three plausible directions, and a small useful change — not a generic lecture on scene structure.

**What it is not.** Not a full word processor. Not a form that demands a genre, an ending, character arcs, or a completed outline. Not a beat-sheet enforcer. Not a generic agent workspace with writing prompts bolted on.

**Two speeds.**

| Mode | Who is driving | What it is for |
|---|---|---|
| **The Room** | The writer, in conversation | Thinking, deciding, planning, giving feedback, directing revisions |
| **The Press** | The tool, unattended | Drafting chapters from a settled plan, with one critique-and-revise pass |

The writer can move between them at any point. The files are the only contract between them.

**How we judge the first release.** A writer can bring their own book, get specific help that understands it, choose the change they want, and trust that their work is still theirs.

---

## 2. What the repository already provides

The working system is smaller and more complete than the phrase "Cowork clone" suggests. Most of the architecture already exists.

| Capability | Where it lives | Status | What is still missing |
|---|---|---|---|
| Library, series, books, plans, provenance | `src/studio/project.py` | Working | A formal library format version and migration path |
| Room chat with file tools, streaming, undo, explore mode, passage selection | `src/studio/chat.py`, `src/app/api.py`, `src/app/static/app.js` | Working | Inline proposal comparison and accept/keep; the editor is a textarea |
| Reader, chapter navigation, selection actions | `src/app/static/app.js` | Working | Focus mode, tracked changes, a real manuscript surface |
| Press: estimate, draft → critique → revise, run folder, report | `src/studio/press.py` | Working | A writer-facing brief before the build; currency estimates |
| Background builds, stop after chapter, progress snapshot | `src/studio/jobs.py` | Working | Durable jobs; recovery after the process dies |
| Providers, roles, reasoning effort, prompt caching, usage log | `src/model_router.py`, `config/settings.yaml` | Working | A budget profile and per-project overrides |
| MCP server and Claude plugin | `src/studio/mcp.py`, `scripts/mcp_server.py`, `.claude-plugin/` | Working | Resources, progress notifications, cancellation, parity tests |
| CLI | `scripts/room.py`, `scripts/press.py`, `src/studio/cli.py` | Working | Nothing urgent |
| Craft guide and conversation skill | `prompts/studio/craft_guide.md`, `.claude/skills/story-session/SKILL.md` | Working, thin | Sourced craft notes and flexible, manuscript-specific advice |
| Markdown export | `src/studio/press.py` | Working | DOCX, then EPUB |
| Tests and CI | `tests/`, `.github/workflows/ci.yml` | Working | Editorial evaluation; MCP contract tests |

**The MCP server is real.** `src/studio/mcp.py` exposes fifteen tools over stdio: `list_books`, `new_book`, `status`, `review`, `ideas`, `rename`, `estimate_build`, `start_build`, `build_status`, `stop_build`, `revise_chapter`, `story_so_far`, `export`, `check`, and `craft_guide`. `.claude-plugin/plugin.json` starts `scripts/mcp_server.py` and passes the library folder and provider keys. Claude in Cowork or Claude Code follows the same story-session skill and edits the plan files directly; the server supplies the operations Claude cannot do with files alone.

That means much of the "Cowork for writing" architecture is already built. The remaining work is not a new platform; it is the writing-specific surface, the craft depth, and the trust features.

---

## 3. Design principles

1. **The writer owns the story; the tool owns the paperwork.** Offer options, keep their words, record only what they agreed to.
2. **Files are the book.** Ordinary Markdown a writer can open, edit, copy, and keep. No database is the source of truth.
3. **Whole book in view, nothing silently retrieved.** Stable material first, the task last. No hidden summarisation, chunking, or vector search.
4. **Two speeds, one set of files.** The Room and the Press read and write the same plan and manuscript.
5. **Lenses, not rules.** Craft guidance is optional and cited; the writer's bible always wins. Specialize in helping writers while leaving room for the writer's imagination and the model's unexpected contributions. Neither a complete outline nor a named method is a prerequisite for useful work.
6. **Every change is visible and reversible.** A change card, a before/after, an Undo that refuses to overwrite newer work.
7. **Explain in writer language.** Errors are fixable sentences, never tracebacks. No protocol jargon outside Settings.
8. **Keep it small.** The repository already deleted a much larger multi-agent pipeline (scene cards, state databases, retrieval, validators) in favour of this design. Do not reintroduce it.

---

## 4. The workspace

Use one book workspace. The document gets the most space; the Room expands during planning and becomes a companion panel while writing.

```text
Library / book switcher         The Glass Harbor                  Saved
┌────────────────┬───────────────────────────────────┬─────────────────────┐
│ The Room       │ Document title + local controls   │ The Room            │
│ Manuscript     │                                   │                     │
│ Story plan     │ Chapter, outline, character sheet │ Your request        │
│ References     │ or proposed change                │ Reading / working   │
│ Drafting       │                                   │ Advice + evidence   │
│                │ The writer's work is central      │                     │
│ Craft notes    │                                   │ Explore / Work      │
│ Settings       │                                   │ Message composer    │
└────────────────┴───────────────────────────────────┴─────────────────────┘
```

The Room is one shared conversation surface. Moving between documents does not create another assistant persona or erase the task. A writer can still start separate chats for separate pieces of work, as the app already does.

| Surface | What the writer sees | Main interaction |
|---|---|---|
| Library | Book covers or quiet title rows, last opened document, series membership | Continue a book, start one, or bring existing material |
| The Room | A task conversation with attached documents and compact action receipts | "Help me make the confrontation less predictable." Open the relevant document alongside it. |
| Manuscript | Chapter list, generous reading column, selection tools, history | Write directly; discuss or revise a selection; compare a suggestion |
| Story plan | Story bible, characters, outline, series bible | Edit the actual Markdown, with a readable view and a source view |
| References | Book and series reference notes, source links, research conversations | Read a reference or decide which findings belong in the book |
| Drafting | Chapter scope, brief, context/call estimate, current stage, results | Draft the next chapter or an explicitly chosen batch; stop after the current chapter |
| Craft notes | The shared guide, its sources, and the book's intentional departures | Read why a lens might help; ask about its application in the Room |
| Settings | Provider setup, role choices, library folder, appearance, connections | Choose where model requests go and inspect connection access |

History, context, and change comparisons are contextual panels, not competing top-level destinations. Review and brainstorming continue to start in conversation; do not add separate Review or Ideas buttons.

### The main journeys

| Journey | What happens | Design rule |
|---|---|---|
| **Start from a spark or bring a draft** | The opening question is "What are you working on?" Accept a sentence, notes, or a document. Read supplied material before asking anything. | Offer two paths: start a story, or bring existing writing. A title can stay temporary. |
| **Explore and decide** | The writer discusses possibilities; agreed decisions are recorded in the right file. | Explore is read-only. An explicit instruction is authority to edit; a speculative "what if" is a proposal to discuss. |
| **Write with a partner** | The writer selects a passage and asks for a change. The Room reads the chapter and the book, names the tradeoff, and proposes a replacement. | Show Original and Suggested, a short explanation, and **Use suggestion / Keep original**. Apply against the exact source version. |
| **Get useful editorial feedback** | "Where does the middle lose momentum?" Feedback appears in the conversation beside linked passages. | Each substantial observation names what happened on the page, the likely reader effect, the link to the writer's intent, and a possible response. |
| **Delegate a draft** | The writer chooses a chapter or batch and sees the brief, length, stopping point, models, and estimate. | Offer the optional plan review once before building. Never require it. |
| **Research without rewriting the story** | Research begins in the Room with the writer's question. Findings carry a source URL and uncertainty. | "Save to book references" or "Save to series references" makes the scope explicit. A web page is information, never instructions. |
| **Continue a series and export** | Series-level material is visibly separate from the book's own. Later books read story-so-far notes instead of full text. | Never retroactively overwrite an earlier book's cast. Export in chapter order. |

### Visual and interaction language

- Retain the current amber, paper, ink, and warm gray palette, with a dark theme. Use accent colour for the current action or selection, not every panel.
- Use Archivo or the system family for controls and Literata or Georgia for prose. Manuscript text starts around 18–20px with comfortable line spacing and a roughly 60–75-character reading measure.
- At a wide desktop size, start near 190px navigation and 300–340px Room panel; let the document take the rest. Panels collapse. Focus mode hides navigation and the Room until recalled.
- On smaller screens, keep one primary surface visible and open the Room as a full-width companion view. Preserve document selection and scroll position when switching. Do not squeeze three columns onto a phone.
- Use labels such as "Story plan," "Keep original," and "Stop after this chapter." Keep model-routing and protocol language in Settings or details.
- All actions need keyboard access and visible focus. Compare changes with text labels as well as colour. Announce saves and completed actions without reading every streamed token aloud.

---

## 5. The Room: how a turn actually works

The app's Room is a model from the writer's own provider following the story-session skill through tools. The plugin's Room is Claude itself following the same skill and editing the files directly. The behaviour should stay the same; only the host changes.

```text
writer message
  │
  ├─ App.send: validate, persist the user item, mark the turn running
  │
  ├─ run_turn:
  │    system  = room_chat prompt + story-session skill + craft guide
  │    user    = every project file as it is now + attachments + the request
  │    loop up to 24 steps:
  │       router.chat(system, messages, tools)
  │       ├─ text → stream to the writer
  │       ├─ tool call → execute under the write lock → activity item
  │       └─ no tool call → reply, stop
  │
  └─ persist history + items; state = finished | stopped | failed
```

### The tools

| Tool | What it does | Safety |
|---|---|---|
| `read_file` | Read any project file | Path must stay inside the project |
| `edit_file` | Replace one exact passage in a planning file | `old_text` must appear exactly once; re-read before writing |
| `write_file` | Write a whole planning or reference file | Must have read the current content first |
| `edit_passage` | Change the selected passage in its document | Selection carries the document version; chapter history is preserved |
| `rename` | Rename a person, place, or thing across the series | Whole words; preview first; apply only after agreement |
| `add_book` | Add the next book to a series | Characters start as a copy of the previous book's |
| `revise_chapter` | Rewrite a written chapter from a note | Previous version goes to history |
| `status` | Chapters, word counts, what is out of date | Read-only |
| `propose_build` | Show a build card with an estimate | The writer presses Build; the model cannot start it |
| `story_so_far` | Write notes later books read instead of full text | Replaces only with history kept |

**Explore mode** exposes only `read_file` and `status`. **Passage selection** is the only way `edit_passage` becomes available. The model sees the selected text and the document path; the app checks the document version again before applying.

### Write safety

- Every planning write re-reads the file and compares it to what the model last saw.
- `edit_file` requires a unique `old_text`; a stale or ambiguous edit fails with a sentence the writer can act on.
- Replacing a file moves the previous text into `.history/` beside it.
- Undo checks that the file still matches the change's `after` text. If the writer edited it since, Undo refuses rather than losing the newer work.
- One planning turn per project at a time. Starting another says: "The Room is already working in this project."
- A stopped or failed turn keeps completed edits and marks the turn interrupted. It never re-applies work silently.

### What the Room is not

It is not a general file agent. It cannot edit chapters through `write_file`; chapters change only through a build, a revision, or a passage edit, so their history stays coherent. It cannot reach outside the project folder. It does not run shell commands.

---

## 6. The Press: how a build actually works

```text
select chapters → estimate → snapshot the plan → for each chapter:
    draft (writer model)
      → critique (a different model)
      → "No changes needed"? ── yes ──► save
      → revise (writer model)
      → revision under 60% of input length? ── yes ──► keep the draft
      → save + provenance
  → report: words, revisions kept, token usage, cost, out-of-date chapters
```

- **The plan is frozen at the start.** `build` reads the `Plan` once and copies it into `runs/<id>/plan/`, so edits made in the Room mid-build cannot split a book across two plans.
- **Chapters build in order.** Each chapter reads the finished chapters before it.
- **One bounded revision by default.** `press.revision_rounds` defaults to 1. "No changes needed" skips the revision. A revision shorter than `min_revision_ratio` (0.6) of its input is discarded.
- **Provenance, not gates.** `.provenance.json` records the outline and background fingerprints each chapter was built from. `status` reports `outline changed` (actionable) or `plan changed` (informational). Nothing blocks on it.
- **Stopping is honest.** Stop finishes the chapter in progress and saves it. The build thread is process-local: closing the browser tab is fine, but quitting the app process ends the build. Say so in the UI.
- **One build per book at a time.** A second request says the book is already building.
- **Failures are explained.** A provider error says which service failed and that finished chapters were saved and nothing half-done was. A failed build saves no unfinished chapter.

The writer should see, before pressing Build: which chapters, the brief, target length, where each chapter ends, which model plays which role, the estimated calls and tokens, and whether an existing chapter will be replaced.

---

## 7. System architecture

```text
┌───────────────────────────── Browser ─────────────────────────────┐
│  SPA (vanilla JS): Library · Project · Chat · Reader · Settings  │
└───────────────▲───────────────────────────────────┬───────────────┘
                │ HTTP + NDJSON (local token)        │
┌───────────────┴───────────────────────────────────▼───────────────┐
│  Local Python process: src/app/server.py (ThreadingHTTPServer)    │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────────────┐ │
│  │ App API     │  │ Room engine  │  │ Press + jobs              │ │
│  │ api.py      │→ │ chat.py      │  │ press.py / jobs.py        │ │
│  └──────┬──────┘  └──────┬───────┘  └─────────────┬─────────────┘ │
│         └────────────────┴──────────────┬─────────┘               │
│                                   ┌─────▼─────┐                   │
│                                   │ Library   │ project.py        │
│                                   └─────┬─────┘                   │
└─────────────────────────────────────────┼─────────────────────────┘
                                          │ Markdown + JSON
                                   library/ (private)
                                          │
                              ┌───────────▼───────────┐
                              │ ModelRouter           │
                              │ roles → providers     │
                              └───────────┬───────────┘
                                          │
              OpenRouter · Anthropic · OpenAI · Google · local
```

The plugin path is parallel, not a second implementation:

```text
Cowork / Claude Code / another MCP host
        │ stdio JSON-RPC
        ▼
scripts/mcp_server.py → src/studio/mcp.py → same studio operations → library/
```

| Process | Responsibility | Lifetime |
|---|---|---|
| Browser SPA | Rendering, selection, streaming display, local preferences | A tab |
| Python app server | HTTP API, Room turns, Press jobs, settings, static files | `python scripts/app.py` |
| Build thread | One chapter loop at a time, one per book | Inside the app process |
| MCP server | Tools for an external host | The host's session |
| CLI | Scripted room and press operations | One command |

There is no cloud service, no database, and no queue. That is a feature at this stage: the whole system is a folder, a Python process, and the writer's provider.

| Concern | Module |
|---|---|
| Library, series, book, plan, provenance | `src/studio/project.py` |
| Prompt assembly (whole-book messages) | `src/studio/prompts.py` |
| Model calls, roles, size limit, usage | `src/studio/llm.py` |
| Room operations | `src/studio/room.py` |
| Press: build loop, estimate, story-so-far, export | `src/studio/press.py` |
| Room chat (tools, undo, review calls) | `src/studio/chat.py` |
| Background builds | `src/studio/jobs.py` |
| App backend, HTTP server, page | `src/app/api.py`, `src/app/server.py`, `src/app/static/` |
| MCP tools and stdio server | `src/studio/mcp.py`, `scripts/mcp_server.py` |
| Model routing, providers, caching | `src/model_router.py`, `config/settings.yaml` |
| Conversation skill and prompts | `.claude/skills/story-session/SKILL.md`, `prompts/studio/` |

---

## 8. Data model

```text
library/                              private by default (gitignored)
  <series>/
    series_bible.md                   shared world, rules, arc across books (series only)
    reference/                        optional: notes every book reads
    chats/
      <chat-id>.json                  conversation, items, history, turn state
      <chat-id>-files/                retained chat attachments
    books/
      01-<book>/
        story_bible.md                premise, feel, world, how it's told, things to keep true
        characters.md                 one "## Name" sheet per character
        outline.md                    "## The threads", then one "## Chapter N" per chapter
        reference/                    optional: notes only this book reads
        manuscript/
          chapter_NN.md               current chapters
          .history/                   every replaced version
          .provenance.json            which plan each chapter was built from
        notes/                        review_*.md, ideas_*.md
        runs/<run-id>/                plan snapshot, draft, critique, revision, report.md
        story_so_far.md               optional: what later books need to know
        export/manuscript.md
```

| File | Format | Contract |
|---|---|---|
| `story_bible.md` | Free Markdown | The writer's intent, world, voice, and things to keep true. The title is the first `# ` heading. |
| `characters.md` | Markdown with `## Name` sections | One sheet per character. "How they talk" sample lines are the most useful field. |
| `outline.md` | Markdown; `## Chapter N` headings | The only required format. Optional `- Words: N` and `- Ends at: ...` lines. |
| `series_bible.md` | Free Markdown | Only when a second book exists. Shared material, never characters. |
| `chapter_NN.md` | Markdown | The manuscript. A leading heading is ignored for word count. |
| `.provenance.json` | JSON | `{ "3": { "outline": hash, "background": hash, "source": "build", "saved": iso } }` |
| `notes/review_*.md` | Markdown | `### N.` points with a blank `**Your call:**` line. |
| `notes/ideas_*.md` | Markdown | Same shape as a review. |
| `runs/<id>/` | Markdown + snapshots | Exactly what the build read, drafted, heard back, and saved. |
| `chats/<id>.json` | JSON | Append-only items and plain-text history; never rewrites earlier turns. |

**Invariants.**

- Each fact lives in one place. Characters only in a book's `characters.md`; shared world only in `series_bible.md`.
- A standalone book is a series of one. `series_bible.md` appears when a second book is added.
- A new book's `characters.md` starts as a copy of the previous book's; earlier books are settled history.
- The writer's manual edits win. Re-read before every change; surface conflicts instead of overwriting.
- Every replacement keeps the previous version in `.history/`.
- Stable material is ordered first so prefix caching works; the task is last.
- No silent truncation or summarisation. If a call is too large, explain the limit and the choices.

**What is missing.** A library format version and a migration note. Add a small `library.json` (or a `format` field in provenance) only when the first breaking change arrives; do not invent a schema for its own sake.

---

## 9. Context strategy

Every call is assembled in the same order:

```text
1. system prompt: role prompt + craft guide
2. series bible
3. series reference notes
4. earlier books (full text, or story_so_far.md when present)
5. this book's story bible
6. this book's characters
7. this book's outline
8. the relevant chapters, in full
9. the task (last, where models attend most reliably)
```

The user message also carries its sections as `parts`, each chapter its own, with `cache_upto` marking where the stable material ends. Anthropic gets a cache marker at that boundary; other providers cache matching prefixes themselves.

**Limits.** `MAX_PROMPT_TOKENS` is 900,000 and refuses an oversized call with a plain explanation. `LONG_PROMPT_TOKENS` is 500,000; the estimate warns above it. `story_so_far.md` is the one deliberate compression, and it is an ordinary file the writer can read and edit.

**The real risk is not fitting the window. It is what a very long window costs and how well it is read.** A 100,000-word book is roughly 130,000 tokens before the plan. Draft + critique + revise can send it three times per chapter. At frontier prices a single book can cost more than the writer expects, and models attend less reliably to the middle of very long prompts.

Proposed mitigations, in order:

1. **A context manifest.** Before a call (or on demand), show what is included and why: series bible 1,240 tokens, chapters 1–11 96,000, task 600, total 118,040 of 900,000. The app already shows a meter; make it explain itself.
2. **A per-book cost and call budget.** Show tokens and, where the provider reports it, currency. Warn before a build that will exceed the writer's budget; do not silently proceed.
3. **Writer-controlled exclusions.** "Revise chapter 12 without re-sending chapters 1–6" is a legitimate request. Let the writer exclude files for one task, visibly, and record it in the change card.
4. **An opt-in long-book mode.** Recent chapters in full plus `story_so_far.md` for the rest, clearly labelled. Not the default, and never silent.
5. **Model tiering.** Full-context model for drafting; a cheaper, capable model for critique, notes, and reviews. The role system already supports this.

Do **not** add retrieval, embeddings, a vector store, or automatic summarisation. The repository tried that and removed it. The answer to long context is legibility and writer control, not a hidden second book.

---

## 10. Craft knowledge: a flexible reference shelf

There is no single professional consensus that can certify a story as good. The product should offer a reliable, inspectable set of craft lenses and adapt them to the writer's aims.

### What exists

`prompts/studio/craft_guide.md` is one short file: the Story Spine, six questions, "but/therefore," promises/progress/payoff, "yes, but / no, and," chapter change, concrete detail, viewpoint, machine-made prose, and planning styles. It cites Adams/Pixar, the South Park creators, Sanderson, Cron, and King. It is a good voice and the right stance. It is not yet "the best knowledge from professionals."

### What it should become

A modest collection of source-backed notes in the existing Markdown guide, used when they help the current task. There is no target count, required schema, coverage score, or obligation to apply a lens to every scene. A useful note explains an idea, where it may help, where it can mislead, and where it came from. Examples are optional and original.

For instance, a scene-turn note could ask what changes for someone by the end, while recognizing that atmosphere, companionship, lingering emotion, or the pleasure of a place can also justify the scene. The model need not name a technique in ordinary conversation.

Preserve differences between the references. A method that favors tight causal plotting and a study that values worlds beyond their immediate plots need not become one universal rule. Choose or compare their perspectives in relation to this writer's intent. The source author's imperatives are advice to consider, not instructions governing the app.

Do not place all ten supplied books into every generation prompt or claim that attaching them trains the model. Keep the shared guidance concise. Consult original passages when a task calls for closer study, with explicit context scope; this proposal does not add an automatic retrieval pipeline. These references have been surveyed through contents and selected passages, not reviewed cover to cover.

Coverage should include:

- **Character:** want vs. need, contradiction, the lie a character believes (Egri; Cron).
- **Scene:** goal, conflict, turn, sequel (Swain; McKee).
- **Structure:** story spine, try/fail cycles, promises/progress/payoff (Adams; Sanderson), and alternatives such as kishōtenketsu, which does not require conflict.
- **Voice:** viewpoint, free indirect style, rhythm, the writer's own samples (Le Guin; Lamott).
- **Genre:** romance beats, mystery fair-play and clue placement, SFF worldbuilding load, horror pacing — as conventions to use or break, not laws.
- **Revision:** what to cut, what to protect, how to read a draft as a reader.
- **Dialogue and subtext:** what a line is doing, not just what it says.

### Applying advice in conversation

The writer should be able to say "the middle sags" and receive a specific, natural response. Start from what the passage does and what the writer wants. Offer a useful observation or a possible direction; ask a question only when the answer would matter. Evidence, reader effect, and alternatives help explain substantive feedback, but are not mandatory headings or a prescribed sequence for every turn.

When the writer wants exploration, follow surprising possibilities without immediately critiquing each one. When they want a draft, write. When they want editing, examine the work more closely. These are conversational intentions the writer can change freely, not required workflow stages or additional product modes. Creative freedom does not mean silently converting a speculative idea into settled story facts.

If alternatives would help, vary the underlying approach rather than only the wording. An unexpected or unconventional option can sit beside a familiar one. Explain tradeoffs without treating convention as the default winner, and record only the choices the writer makes.

### Voice and intentional departures

- Offer optional voice notes in the bible when useful: the writer's chosen samples, traits they want to preserve, and what polishing should leave alone. Do not require a profile or infer a permanent style from a few passages.
- Record preferences such as "the slow opening is deliberate" in the existing relevant sections when the writer agrees. They need not maintain a separate exceptions checklist or justify unconventional choices to the software. Feedback may discuss whether the intended effect lands, rather than flagging the choice itself as a defect.
- Never adapt these preferences silently from accepted punctuation changes. Propose a change; the writer approves it.

### Sourcing and ethics

- Cite specific works and, where possible, specific lessons. Write original summaries; do not reproduce substantial copyrighted text.
- Never imply that a professional personally assessed this manuscript or endorses the tool.
- Have a human editor review each lens for accuracy and usefulness before it ships.
- Broaden beyond commercial Anglophone speculative fiction. Include translated and non-Western traditions, romance, mystery, literary fiction, and children's fiction.
- Keep the guide's stance: lenses, not rules. No required beats, percentages, arc fields, or numeric quality scores.

The priority order is: current explicit task and agreed intent, current book/series facts, then applicable craft guidance. If the task contradicts settled facts or a manual edit, surface the conflict. Never let an expert's preferred method outrank the writer.

---

## 11. MCP and integrations

MCP standardises connections between a host and capabilities such as tools, resources, and prompts. It does not itself provide editorial expertise. [MCP architecture overview](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture)

Keep two directions distinct:

```text
Our browser app ──direct calls──► studio operations ──► book files
Other MCP host  ──our MCP server─► studio operations ──► book files

Later, if needed:
Our app ──outbound MCP client──► chosen research/document service
```

The first two paths exist. A general outbound MCP connection manager would be new work. The app's configured provider-side web tools cover initial research; do not build an outbound client just to reproduce that capability.

### What the server should add

| Gap | Why it matters | Proposal |
|---|---|---|
| No resources | A host cannot browse the plan or chapters natively | Expose `library://books`, `book://<id>/outline`, `chapter://<id>/<n>` as read-only resources |
| No prompts | Each host must know the skill by convention | Expose the story-session skill and a few starter prompts |
| No progress | Long builds look frozen | Send MCP progress notifications per stage |
| No cancellation | Hosts cannot stop a build cleanly | Map cancellation to the existing stop-after-chapter behaviour |
| No library selection per call | One library per server process | Keep the environment default; add an optional `library` argument only if real hosts need it |
| Parity by hand | App and MCP tools drift | A contract test that every studio operation used by one surface exists in the other |

Keep the server stdio-only and local. It is a bridge to the writer's own files, not a hosted service. If an outbound connection is added later, order it: a source-fetch/research tool, then a reader's reference library, then document import/export. Start with bounded reads, visible selected sources, explicit file destinations for writes, and failure isolation. A connector failing must not prevent writing or local file access.

Public comparison points, documentation-level only: [novel-writer-mcp](https://github.com/novacastriancyber/novel-writer-mcp) overlaps heavily with this repository; [mcp-writing](https://github.com/hannasdev/mcp-writing) uses a scene index and SQLite-canonical metadata, which conflicts with this project's whole-book, plain-file design. Retain our server; use external MCP only for a specific missing capability.

---

## 12. API, state, and recovery

The app is a small HTTP API over the studio operations. The browser never talks to a model directly.

| Group | Routes |
|---|---|
| Library | `GET /api/state`, `GET /api/project`, `POST /api/projects` |
| Files | `GET /api/file`, `POST /api/file`, `POST /api/reference`, `POST /api/reference/remove`, `POST /api/attachment` |
| Chats | `GET /api/chat`, `POST /api/chats`, `POST /api/send`, `POST /api/send/stream`, `POST /api/chat/stop`, `POST /api/chat/attachment/remove` |
| Changes | `POST /api/undo`, `POST /api/review/call` |
| Press | `GET /api/estimate`, `POST /api/build`, `POST /api/build/decline`, `POST /api/build/stop`, `GET /api/build`, `POST /api/export` |
| Settings | `GET /api/settings`, `POST /api/settings/key`, `POST /api/settings/check`, `POST /api/settings/role`, `POST /api/settings/effort`, `POST /api/settings/press` |

All calls carry a per-run token in `X-Writers-Room-Token`; the server refuses a non-local `Host`. `/api/send/stream` emits newline-delimited JSON events: `started`, `phase`, `text`, `item`, `error`, `done`.

**Chat record.** Append-only by design:

```json
{
  "id": "c202610271200001",
  "project": "the-glass-harbor",
  "title": "Make the confrontation less predictable",
  "book": "01-the-glass-harbor",
  "items": [
    {"kind": "user", "id": "m...", "text": "...", "selection": null, "explore": false},
    {"kind": "activity", "id": "a...", "verb": "Edited", "file": "books/01.../outline.md",
     "text": "Raised the stakes in chapter 9", "before": "...", "after": "..."},
    {"kind": "approval", "id": "b...", "book": "01-the-glass-harbor", "which": "next",
     "numbers": [12], "title": "Build chapter 12?", "detail": "...", "status": "pending"},
    {"kind": "assistant", "id": "m...", "text": "..."}
  ],
  "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}],
  "attachments": [{"name": "canon.md", "scope": "chat", "path": "chats/c...-files/canon.md"}],
  "turn": {"id": "t...", "state": "finished", "phase": ""}
}
```

- Earlier turns are sent as plain text and never rewritten. This keeps prompt caching and provider reasoning binding intact.
- The current files are sent only with the newest message. The model is told the files win over anything said earlier.
- Chat saves are atomic (temporary file, then replace). A turn that was running when the process stopped is marked interrupted on reopen; completed items remain.
- One turn per project, one build per book. Writes share a lock; reads do not.

### Proposals

The passage workflow needs a first-class proposal, not just a chat message. Store it in the chat record:

```json
{
  "kind": "proposal",
  "id": "p...",
  "path": "books/01-the-glass-harbor/manuscript/chapter_03.md",
  "expected_version": "sha256...",
  "scope": {"start": 1200, "end": 1480},
  "before": "the exact selected text",
  "after": "the suggested replacement",
  "explanation": "one or two sentences",
  "status": "pending | accepted | rejected | stale",
  "created": "2026-10-27T12:00:00"
}
```

Rules: persist before showing; apply once; re-read and compare `expected_version` at acceptance; if the file changed, mark `stale`, keep both versions, and offer to regenerate or resolve. A proposal is interaction data, not story truth. The files remain authoritative.

### Recovery states

| Situation | Expected behaviour |
|---|---|
| Empty book | Invite a spark, notes, or a draft; offer a next move without an intake form |
| No provider key | Allow reading and manual editing; explain setup when a model action is requested |
| Model/network failure | Keep the writer's text, completed items, and clear retry scope; retry must not duplicate applied edits |
| File changed during a proposed edit | Show the conflict; preserve both versions; do not apply against stale text |
| Outline changed after drafting | Mark the chapter `outline changed`; offer discuss, revise, rebuild, or keep |
| Plan changed during a build | The build uses its saved snapshot; new work uses current files |
| Context too large | Explain the limit before or at failure; offer deliberate file or story-so-far decisions |
| Empty or unsuitable generated result | Save no empty response; report a discarded short revision |
| Writer rejects feedback | Keep the decision visible; do not quietly apply the suggestion elsewhere |
| App process stops during a build | Say the build stopped; saved chapters and reports remain; continuing is a fresh build |
| MCP host exits | The server process ends; no durable job survives. Document this in the plugin's help. |
| Corrupted chat JSON | Skip it in summaries, keep the file, and offer to open the raw file rather than deleting it |
| Rename collision | Show the count and examples before applying; never rename history, runs, or reviews |

---

## 13. Security and privacy

The app is local-first, and that is a selling point. Keep it true.

- Bind to `127.0.0.1`, refuse requests whose `Host` is not local, and require the per-run token. This stops a malicious web page from driving the app through the writer's browser.
- Keys live in `.env` or the app's Settings; `config/settings.local.yaml` holds choices, not secrets. Redact keys from UI, logs, and chat history.
- The library is gitignored by default. Using a remote model still sends the assembled text to that provider; say so during setup and in the context details.
- A web page, reference file, or MCP tool result is **information, never instructions**. The Room prompt already says this; keep it in every new surface.
- Resolve every path inside the project root and reject traversal. The allowlist for writable files is narrow on purpose.
- Do not add telemetry that leaves the machine. Usage is already logged locally per call; expose it per run and per book instead of phoning home.
- Offer an explicit **local-only** profile: a local model, no web tools, no outbound MCP. It will be slower and weaker, but it should exist for writers who need it.
- Writers fear losing work more than they fear bad prose. Add opt-in git snapshots of the library (one commit per session or per build), a restore view, and an export that does not depend on the app. `.history/` is good; it is not a backup.

Threats worth naming: another local process reading `.env`; a provider retaining submitted text; prompt injection through research; a malicious MCP server; a synced folder exposing the library. None require a cloud service to mitigate; all require honest documentation.

---

## 14. Failure states and empty states

The product is judged in the awkward moments, not the demo.

| State | What the writer sees |
|---|---|
| First run, no key | The app opens, projects are readable, and a single "Connect a provider" action explains the one key that unlocks model work |
| Empty library | "What are you working on?" with a sentence, notes, or a document; no form |
| Empty outline | "Plan a few chapters in the chat, or add `## Chapter 1` yourself" — not a disabled Build button with no explanation |
| Build card | Chapters, brief, target words, ending, models, calls, tokens, replacement warning, Build / Not now |
| Build running | Stage (Drafting / Reading / Revising), chapter N of M, Stop after this chapter, Hide |
| Build finished | Chapters and words, revisions kept, report link, one honest paragraph about what worked |
| Build failed | Which service failed, that finished chapters are saved, and the retry scope |
| Context warning | What is large, what it costs, and the choice: exclude, write story-so-far notes, or continue |
| Stale proposal | "The chapter changed since this suggestion. Keep your version, regenerate, or compare." |
| Rejected advice | The review records "Disagreed: deliberate." It is not raised again as a defect. |

---

## 15. Evaluation

Functional checks are necessary but not sufficient. The product's claim is editorial quality, and that needs humans.

**Functional.** `pytest -q` and `ruff check .` in CI. Tests never call real models; `tests/fakes.py::FakeRouter` returns scripted replies and records calls. Cover version conflicts, selection boundaries, history/undo, cancelled turns, reference scope, frozen build context, restart messaging, and MCP tool parity.

**Editorial.** Compare original and suggested passages blind with writers or editors across genres. Ask:

- Does the revision better serve the stated intent?
- Does it preserve the writer's voice and characteristic phrasing?
- Does it introduce a contradiction or invent a fact?
- Is the explanation specific to this manuscript, or generic advice?
- Did it respect a deliberate choice?

Include difficult cases: a deliberately slow scene, an unreliable narrator, a static character arc, stylized grammar, sparse outlining, a writer declining advice, and a late series reveal. Measure unsupported critique claims and unwanted changes as well as useful suggestions.

**Cost and latency.** Tokens per call, cost per chapter and per book, wall-clock time per chapter, cache hit rate, and the share of calls that exceed the long-prompt warning. Put these in the run report; no dashboard is needed yet.

**Instrumentation without surveillance.** Keep the local usage log. Add a per-run summary. Do not add a phone-home analytics service, and do not equate acceptance rate, word count, or a model's self-score with quality.

Evaluation fixtures are development tools, not mandatory story validators or runtime gates.

---

## 16. Delivery plan

The order is chosen so that each slice is useful on its own and proves the next one.

### Slice 1 — A passage becomes better without losing control (2 weeks)

Open a chapter, select a passage, state a goal, discuss the effect, compare a suggestion, accept or keep the original, undo. This is the shortest demonstration of the product promise.

**Acceptance:** a proposal is stored before display; acceptance applies against the exact version; a stale proposal preserves both texts; the previous chapter version is in `.history/`; the writer can reject and nothing changes; `pytest` and `ruff` pass.

### Slice 2 — The book becomes navigable (2–3 weeks)

A document-centred project page, story-plan views that edit the real Markdown, references with visible scope, a shared Room across documents, focus mode, and a context manifest.

**Acceptance:** the writer can move from library to chapter to outline without losing the Room; the context panel names what was sent and its token size; manual edits still win; mobile shows one surface at a time.

### Slice 3 — Craft knowledge earns the claim (3–4 weeks)

A small, useful set of sourced craft notes, flexible editorial conversations, and optional voice preferences. The craft guide remains the single home; the skill and prompts point at it. Choose coverage from actual writing needs, without a quota of lenses or a required critique workflow.

**Acceptance:** shipped advice is attributed and its limits are clear; a writer can move from "my middle sags" to useful help, or ask for free exploration without a diagnosis first; deliberate choices are evaluated against their intended effect; no required profiles, beats, or quality scores appear anywhere.

### Slice 4 — Delegation is understandable (2 weeks)

A build brief card, stage display, stop and recovery messaging, a report the writer can read, and token/currency estimates where the provider supplies pricing.

**Acceptance:** before a build the writer sees chapters, length, ending, models, calls, and tokens; stopping finishes the current chapter; a failed build explains what was saved; the report links from the chat.

### Slice 5 — Trust and export (1–2 weeks)

Opt-in git snapshots and restore, DOCX export with chapter headings and page breaks, and better import (DOCX structure, a proposed organisation before splitting a manuscript).

**Acceptance:** a writer can restore a previous state without the app; DOCX opens with headings and page breaks; import never silently overwrites an existing file.

### Slice 6 — MCP native (1–2 weeks)

Resources for plans and chapters, prompts for the skill, progress notifications, cancellation, and a parity contract test.

**Acceptance:** a host can list a book's plan and chapters without shell access; a long build reports progress; cancellation stops after the chapter in progress; the app and MCP surfaces expose the same operations.

**Later:** EPUB, outbound research MCP, a desktop wrapper, collaboration, screenplay and nonfiction workflows. No model swarm, vector database, mandatory beat sheet, numeric quality score, automatic endless polish, or new story-state database is needed for these slices.

---

## 17. Risks and open questions

| Risk | Why it matters | Mitigation |
|---|---|---|
| **Context economics** | Whole-book calls are the product's differentiator and its biggest cost and latency risk | Context manifest, budgets, exclusions, opt-in long-book mode, model tiering — not retrieval |
| **Prose quality is table stakes** | Many tools can draft, critique, and revise; the loop alone is not a moat | Win on editorial specificity, voice preservation, craft knowledge, and the planning conversation |
| **Scope creep toward a word processor** | A mediocre editor is worse than a great companion | Keep the manuscript surface a reader with selective editing; integrate with real editors later if needed |
| **Craft IP and quality** | Summarising and citing professionals badly damages trust | Original summaries, specific citations, human editor review, no impersonation, licence care |
| **Provider and model churn** | A stale model ID is the most common first-run failure; prices and availability move | Verify shipped IDs at release; per-role overrides; a clear "model unavailable" message |
| **Single-user local architecture** | No sync, backup, or collaboration; one process owns jobs | Be explicit; add git snapshots and export; revisit only if writers ask |
| **MCP host fragmentation** | Cowork, Claude Code, and other hosts differ in resources, progress, and auth | Keep the server small and standards-based; test against real hosts; do not depend on one host |
| **Evaluation cost** | Blind human comparison is slow and expensive | Start with 20–30 passages across 4–5 genres; reuse fixtures; measure a few clear dimensions |

**Open questions for the writer building this.**

1. **Which host is primary?** The local app, or Cowork/Claude Code with the plugin? That decides whether the next investment is the document surface or the MCP surface.
2. **Who is the first writer?** A beginner who needs confidence, or an experienced writer who needs leverage? The craft guide's tone and the review's directness should differ.
3. **Which genre first?** Romance, mystery, SFF, and literary fiction have different conventions and different readers for evaluation. A focused first lens library beats a shallow universal one.
4. **What is the budget per book?** If it is a few dollars, the whole-book strategy needs a cheaper tier. If it is tens of dollars, the current design is viable.
5. **Is local-only a requirement?** If yes, the local model profile and the no-web mode become first-class, not an afterthought.
6. **Is collaboration needed?** If two writers share a book, the plain-file contract still works, but chat and job ownership need a story.

---

## 18. What would make this fail

Not competition. These:

- Building the generic Cowork shell and assuming writing depth will follow.
- Adding more agents, retrieval, and validators because the output is not good enough, instead of improving the craft guidance and the revision UX.
- Letting the whole-book promise become an expensive, slow, unreliable default with no visibility.
- Shipping a craft guide that is one person's opinions dressed as professional consensus.
- Treating the writer's manual edits as an obstacle to be reconciled rather than the truth.
- Forgetting that the writer must be able to leave with their book.

The repository's existing discipline — plain files, one skill, two speeds, no machinery the model does not need — is the right foundation. The work now is depth, not architecture.
