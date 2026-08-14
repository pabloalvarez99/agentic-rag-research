# ADR-0004 — Notes are a typed store, and the free-path critic is not a model

- **Status:** accepted
- **Date:** 2026-08-14
- **Scope:** what a run remembers between steps, what the stop rule is allowed to score,
  and why the component that decides sufficiency contains no provider call

## Context

Until now a run's memory was `ResearchState.evidence`: a deduplicated list of
`Passage` objects, in the order a backend returned them. That is a buffer, not a
store. It answers one question — *what came back?* — and the three questions an
auditor actually asks are answered only by reading passage text and reconstructing the
mapping by hand:

- Which claim is this run relying on?
- Where did that claim come from?
- Can I follow it back to something I can check?

The stop rule made the gap concrete. It scored

```
score = len(evidence) + question terms covered by evidence
```

The first half is a length. Five passages about the wrong thing clear a threshold of
three on their own, and nothing in the trace distinguishes that run from one resting on
five passages that answer the question. The second half read passage text *and* heading
path *and* title, so a chunk could contribute coverage through a document title the run
never relied on for anything.

Neither half was wrong so much as untyped: both scored a container the retriever
filled, rather than a thing the run had committed to.

There is a second pressure. `search_notes` — the tool the critic may request before
synthesis — was named for notes and ranked passages, because there were no notes. A tool
whose name describes a concept the codebase does not have is a tool nobody can reason
about.

## Decision

**A run writes notes, the notes are the store, and the stop rule scores the store.**

1. **`Note` is a typed record with four fields**: `id`, `claim`, `source`, and an
   optional `citation`. It lives in `agentic_rag/notes.py` at the package root, beside
   `text.py`, and imports nothing at runtime — the agent writes notes and the tools rank
   them, so a note that lived inside either package would make the two import each
   other.
2. **`claim` is the retrieved chunk, verbatim**, whitespace-collapsed and bounded at
   `MAX_CLAIM_CHARS`. Collapsing whitespace is the only edit, and it exists so two
   backends that differ in line wrapping produce the same note for the same chunk.
   Nothing rewrites, summarises, or selects.
3. **`citation` is the chunk id, or `None`.** Grounding is a property that is *checked*,
   never assumed. The free path produces only grounded notes, so the ungrounded branch
   is a measured zero rather than an untested one.
4. **`source` is carried and never resolved.** Same rule as `Passage.source_path`: it
   arrives from a retrieval service, so treating it as a filesystem path would turn a
   hostile corpus into a file read.
5. **The state mints ids and traces every write.** `record_note` assigns `note-1`,
   `note-2`, … in add order, refuses a duplicate `(citation, claim)` pair, and emits a
   `note_added` event carrying the whole note. A claim that entered a run without a
   trace event is a claim nobody can date.
6. **The stop rule scores grounded, on-topic notes:**

   ```
   score = question terms covered by grounded claims + count of grounded, on-topic notes
   ```

   A note counts only when a chunk id backs it and its claim shares at least one term
   with the question. `Critique` carries `note_count`, `grounded_note_count`,
   `relevant_note_count` and `keyword_overlap` alongside the verdict, so the decision is
   recomputable from the trace by hand.
7. **`search_notes` searches notes.** It ranks the run's own store by lexical overlap
   with the question, ties broken by insertion order. It still cannot retrieve, generate,
   or contact a provider, and it still does not spend a retrieval step.
8. **The critic contains no model call, and this is a decision rather than a stage.**

## Why the free-path critic is not an LLM

The obvious upgrade is to ask a model whether the evidence answers the question. It is
the component of this loop most people would reach for a model for, and it is the one
place a model does the most damage at this milestone.

- **It would make the stop rule unfalsifiable.** Today `score`, its four inputs and the
  threshold are all in the trace, so a reviewer who disagrees with a refusal can
  recompute the arithmetic and point at the number they dispute. "The judge said no" is
  not a claim anyone can check, and a stop decision nobody can dispute is a stop
  decision nobody can audit.
- **It would end determinism, and determinism is what the tests are made of.** The same
  question under the same budget currently produces a byte-identical trace, which is
  what lets `data/eval/golden_research.jsonl` assert on 17 exact outcomes and what will
  let a downloaded trace be compared against a hosted one.
- **It would put a credential on the default path.** The whole point of the fixture path
  is that the control flow, the budget accounting, the trace and the refusal are
  exercisable with no key and no network. A judge behind an API key means CI either
  holds a secret or stops testing the stop rule.
- **The failure it would hide is the expensive one.** A model asked "is this enough?"
  answers "yes" far too readily. The loop's most valuable behaviour is refusing, and
  wiring the refusal path to a component with a documented bias toward agreement would
  quietly remove it.
- **The honest description of what a model would add is different evidence, not a better
  number.** An LLM critic is worth having when there is a labelled set to measure it
  against. There is none yet, so adopting one now would replace a rule that is merely
  crude with one that is crude *and* unmeasurable.

The seam is already where it needs to be: `critique()` is a pure function from a
question and a note store to a verdict. A model-backed implementation is a second
implementation behind that signature, arriving with the labelled set that can show it is
better — the same shape the retrieval boundary uses for the fake and HTTP backends.

## What this does not decide

**Notes are still one per chunk.** Nothing splits a chunk into several claims or merges
two chunks into one. Both need a component that can honestly narrow text, which is the
thing this ADR declines to add on the free path.

**Ungrounded notes are not produced.** The type admits `citation=None` and the critic
scores it as zero, but no code path writes one. That branch exists for a future
component — a synthesis step, a user-supplied assumption — and it is scored today so it
cannot arrive unscored.

**`evidence` remains.** The passage list still exists and still drives citations and the
report: markers resolve to retrieved passages, in first-seen order. Notes are what the
run reasons over; passages are what a citation points at. Collapsing them is a bigger
change than this ADR needed to make.

## Alternatives considered

**Keep scoring passages; just drop the length term.** The smallest change. Rejected
because it fixes the arithmetic without answering any of the three auditor questions:
there is still no typed thing to point at when asking what a run relied on, and
`search_notes` still ranks something that is not a note.

**Take the first sentence of a chunk as the claim.** Attractive: a claim should be a
sentence, and the first sentence of a heading-structured chunk usually is one. Rejected
after measuring it. On this corpus it dropped the loop's term coverage far enough to
turn answerable demo questions into refusals — a chunk that opens with context and
states its claim second is common, and the failure is *silent*, because the citation
still resolves and nothing in the trace looks wrong. Sentence selection is a
summarisation decision, and the free path has nothing that can make it honestly.

**Store a note per sub-question rather than per chunk.** Closer to how a person takes
notes. Rejected because a note would then aggregate several chunks and its `citation`
would have to become a list, at which point "which chunk says this?" is exactly as
unanswerable as it was before.

**Let the critic write notes.** Tempting, since the critic is what decides what matters.
Rejected: the critic is the only component that can end the loop on success, and a
component that both produces the evidence and judges it can always find itself
sufficient. Notes are written by the retrieval node; the critic only reads them.

## Consequences

**Bought.** "What is this run relying on, and what backs it?" is a typed query against a
store rather than an exercise in reading passage text. Every claim has a trace event
carrying its id, its source and its grounding. The stop rule can no longer be cleared by
volume alone, and its arithmetic is still hand-checkable from the trace.
`search_notes` now searches the thing it is named after.

**Accepted costs.** There are two representations of retrieved text in a run — the
passage and the claim lifted from it — and while the claim is the chunk verbatim they
are near-copies. That is the price of separating what a backend returned from what the
run committed to, and it becomes load-bearing the moment a claim is anything narrower
than a chunk. The trace is also longer: one `note_added` event per new passage.

**Checkable.** `tests/test_notes_store.py` covers the type, the id sequence, the
duplicate rule and the trace event; `tests/test_agent_components.py` covers the scoring
of ungrounded and off-topic notes; `tests/test_research_loop.py` asserts the whole event
order including `note_added`. The 17 goldens in
[`data/eval/golden_research.jsonl`](../../data/eval/golden_research.jsonl) pass unchanged
under the new rule — the scoring change was verified against them rather than accepted
on the strength of the argument for it.
