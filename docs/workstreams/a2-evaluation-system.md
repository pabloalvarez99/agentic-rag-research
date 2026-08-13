# A2 — Offline evaluation system

Owner of `src/agentic_rag/evals/**`, `data/eval/**`, `tests/evals/**`,
`reports/evals/**`. Branch `feat/p2-evaluation-system`.

This document is the lane's reasoning: what the evaluation measures, what it
refuses to claim, how it is defended against measuring itself, and what it found.

---

## 1. What the problem actually is

Writing an evaluation harness is easy. Writing one that can be trusted by someone
who did not write it is the hard part, because a harness is authored by the same
person who wants it to pass. Three failure modes follow from that, and each one
produces a green scorecard that means nothing:

| Failure | How it looks | Why it is tempting |
|---|---|---|
| **Leakage** | Expectations copied from what the implementation printed | It makes the dataset pass on the first run |
| **Reward hacking** | Thresholds relaxed, datasets shrunk, gates narrowed until they clear | Every individual step looks like a small fix |
| **Overclaiming** | Fixture numbers quoted as retrieval quality, answer quality or latency | The numbers are real; only the label is wrong |

Everything below is arranged against those three.

## 2. Threat model

Ordered by how likely they are to actually happen here, not by how dramatic they
sound. Each has a defence that is mechanical — something in the code or the suite,
not a promise in a document.

### 2.1 An expectation records the output instead of deriving it

The failure: run the loop, see what it does, write that down as the expectation.
The dataset then passes forever and detects nothing, including a regression that
was present when the expectation was written.

Defences, in order of strength:

1. **The schema cannot hold an output.** `EvalCase` sets `extra="forbid"` and has
   no field for a report, an answer or a snippet. A case can constrain *how a run
   behaved*; it has nowhere to write *what it said*.
   Test: `test_no_case_can_carry_an_answer`.
2. **Every expectation is re-derived independently.** `tests/evals/spec_model.py`
   implements the documented rules — the planner's split and cap, the critic's
   score and threshold, the outcome table, the fixture's overlap ranking — and
   imports nothing from `agentic_rag.agent`. Every golden expectation is checked
   against it.
   Test: `test_every_expectation_is_derivable_from_the_documented_rules`.
3. **The docs and the code are checked against each other.** The same model is run
   against the real loop over all 66 questions. A disagreement is not a test to
   fix: it means `docs/architecture.md` and the implementation have drifted.
   Test: `test_whole_loop_agrees_on_every_golden_question`.
4. **Each case states its derivation.** `rationale` names the rule the expectation
   follows from, so a reviewer can check it by reading, without running anything.

**Residual risk, stated plainly:** the spec model was written by someone who had
read the implementation. It is independent in construction, not in origin. It
would catch a rule the code and docs disagree about; it would not catch a rule
that is wrong in the same way in both. Closing that needs a second author working
only from `docs/architecture.md`.

### 2.2 The harness is tuned until it passes

The failure: a gate fires, and the cheapest fix is to soften the gate.

Defences:

- **The dataset floor is enforced on every run.** `--minimum-cases` defaults to 48
  and the run exits `3` below it, so a dataset cannot be quietly shrunk to the
  cases that pass. Raising it past the dataset still fails, which is asserted.
- **The only threshold knob makes the run stricter.** `--strict` adds failures; there
  is no flag that removes one. A gate cannot be loosened from the command line.
- **The invariant list is asserted explicitly** in `test_the_invariant_set_has_not_shrunk`,
  so removing a gate is a visible test change rather than a silent deletion.
- **Nothing in the runner knows a case id.** Every case takes the same path.

### 2.3 The harness would pass anything

The failure, and the one most easily missed: a green scorecard proves nothing
unless the harness can produce a red one.

Defence: `tests/evals/broken_runners.py` holds six implementations, each broken in
one specific way, and `evaluate_case` takes the runner as a parameter so they can
be evaluated by the real harness. `test_negative_controls.py` asserts each one is
caught.

| Broken implementation | Caught by |
|---|---|
| Fabricates a citation to a passage that does not exist | `citations_resolve`, `provenance_is_real` (gate) |
| Prints a marker with no citation behind it | `citations_resolve` (gate) |
| Spends more steps than the case allowed | `budget_respected` (gate) |
| Answers confidently and cites nothing | `cite_or_refuse` (gate) |
| Retrieves before recording a plan | `plan_precedes_tools`, `trace_contract` (gate) |
| Refuses every question | `unexpected_refusal_rate` = 100%, agreement drops (metric) |

The last row is the interesting one and it is documented as a deliberate
asymmetry: **refusing everything breaks no invariant.** The gates check that a run
is well formed, not that it is useful, so a loop that answers nothing is
structurally valid. Only the expectation metrics catch it. An invariant that also
fired there would be an invariant that punished honest refusals — the behaviour
this project most wants to keep. Recorded as
`test_refusing_everything_passes_the_gates_and_that_is_the_point`.

### 2.4 A fixture result is quoted as a quality result

The failure: "100% citation validity" travels without "on a five-passage
in-process fixture".

Defences: every artifact carries `evidence_class: fixture-contract` and a
disclaimer as its first line; the Markdown ends with an explicit list of what the
scorecard does not measure; the renderer is asserted never to contain the words
"SOTA", "state of the art" or "outperform"; and **no timing is recorded anywhere**,
deliberately, so no latency claim can be assembled from the artifact even by
someone trying.

### 2.5 An evaluation silently becomes a billed one

The failure: `build_retrieve_tool()` reads `PRODUCTION_RAG_URL`. A shell that
happens to have it set would send an evaluation over the network.

Defences: the runner constructs the fixture explicitly and never calls that
factory; every run's own trace records which backend served each step, and
`backend_is_the_bound_one` fails if any names another; the `$0 billed` line is
printed only when `free_path_share` is 1.0 over a non-zero denominator, so the
claim rests on the records rather than on the code path looking free; and the
offline tests poison `socket.socket`, `socket.create_connection`, `httpx.Client`
and `httpx.AsyncClient`, then run the whole dataset with `PRODUCTION_RAG_URL` set
and assert the artifact is byte-identical to a run without it.

---

## 3. What is a gate and what is a number

The split is the design. Confusing the two is what makes evaluation harnesses
either useless or dishonest.

**Hard invariants** are properties of *any* run of *any* question. A violation is a
defect no curation can excuse, and it exits `1`.

| Invariant | Property |
|---|---|
| `budget_respected` | Steps never exceed the case's budget; the trace agrees with the state |
| `terminal_outcome` | The run ends terminal, with a closed-set reason and a report |
| `trace_contract` | Opens with a plan, pairs every call with a result, ends with `stop` |
| `plan_precedes_tools` | A capped, non-empty plan is recorded before any tool runs |
| `citations_resolve` | Markers are 1..n in order and each resolves to a retrieved passage |
| `provenance_is_real` | No cited chunk id or source path is from outside the corpus |
| `evidence_deduplicated` | A chunk two steps returned is stored, and cited, once |
| `cite_or_refuse` | An answer carries citations; a run with no evidence refuses |
| `backend_is_the_bound_one` | Every result names the backend the runner bound |
| `gaps_are_reported` | Every gap the critic named appears in the report |
| `deterministic_output` | Repeating the evaluation produces identical case records |
| `surface_form_invariance` | Cases differing only in surface form behave identically |

**Descriptive metrics** measure agreement between a curated expectation and an
implementation. Agreement can drop because the loop regressed *or* because the
expectation was wrong, and only a reader can tell which. Making that a gate would
make the honest fix (correct the expectation) indistinguishable from the
dishonest one (loosen the threshold). They are reported and do not fail the run,
unless `--strict` is passed.

### Denominators

Every metric carries its numerator, its denominator and what the denominator
counts. Two rules, both from the same failure:

- **The denominator is chosen so the metric can fail.** `expected_source_match` is
  over *cases that declare expected source paths*, not over all cases. A rate over
  all cases, most of which declare a floor of zero, reads 100% forever.
- **A zero denominator is undefined, not perfect.** `MetricValue.build` returns
  `value: null` with the reason stated. A slice that stopped being covered must
  read as missing coverage, never as a clean sweep.
  Test: `test_an_undefined_rate_prints_as_undefined_not_as_perfect`.

---

## 4. The dataset

66 cases over six behaviour slices; curation, provenance and licence are in
[`data/eval/README.md`](../../data/eval/README.md). Fourteen integrity rules reject
a dataset before anything is evaluated, each with a test that breaks it on purpose.

The floor in the brief is 48. The file holds 66 because the slices needed
different amounts of evidence — the refusal slice needs both ways of refusing, the
normalisation slice needs pairs, and the multi-concept slice needed cases where
the plan is actually walked (§5.1).

---

## 5. Findings

These are results, not test failures. Each is a fact about the loop that the
evaluation produced and that was not obvious beforehand.

### 5.1 The plan is mostly decorative on this fixture

Nine of the twelve multi-concept cases finish in **one** step. The critic scores the
evidence against the *whole* question rather than the current sub-question, so a
passage that covers the compound question satisfies the threshold immediately and
the remaining sub-questions are never retrieved.

Consequence for the dataset: the multi-concept slice asserts
`expected_min_plan_size >= 2` — a planner-rule constraint that is defensible — and
three cases were added whose first sub-question is deliberately off-corpus, so the
loop must reach the second one before it can answer at all. Those three are what
would catch a loop that plans and then ignores its plan.

This is worth stating in the architecture's terms: the sufficiency threshold is
documented as "a constant with no evidence behind it", and this is the first
evidence about it. A threshold of 3 over a five-passage corpus is met by a single
retrieval for most questions, which means the loop rarely loops.

### 5.2 On one case the loop gathers *less* evidence than no loop at all

`multi-concept-ingest-and-answer-stage` — "What does the ingest step do with
heading structure and what does the answer step do with a citation marker?"

- Single retrieval pass over the whole question: **3 distinct passages**.
- The bounded loop: **1 passage**.

The planner splits the question, the first sub-question retrieves the ingest
passage alone, and the critic — scoring against the whole question — accepts and
stops. Splitting narrowed the query, and stopping early kept it narrow.

This is a negative result for the loop, on its own fixture, produced by its own
evaluation. It is left in the dataset and in the scorecard rather than removed.
It is also the reason the single-pass reference exists at all.

### 5.3 Every hard invariant holds on the current implementation

12/12, over 66 cases, stable across three repeats. Stated with its limits: the
gates were written against this loop's documented contract, and the negative
controls establish they discriminate. They do not establish that the contract is
the right one.

### 5.4 The artifact reproduces byte for byte from a clean clone

Verified rather than assumed — §7.

---

## 6. What this system deliberately does not do

- **No quality claim of any kind.** Not retrieval quality, not answer quality, not
  faithfulness. The backend is lexical overlap over five committed passages and
  the synthesiser writes no prose, so there is nothing to be unfaithful *to*.
- **No latency claim.** No duration is recorded anywhere. A test walks every key
  in the artifact and fails on `duration`, `elapsed`, `latency`, `seconds`,
  `millis` or `took`.
- **No comparison with any other system.** The only reference is a single
  retrieval pass over the same fixture, labelled control-flow-only everywhere it
  appears.
- **No paid judge, no model-graded metric, no network.** Every number comes from
  the run's own records.
- **No production-readiness claim.** Every run is in-process against a fixture.

---

## 7. Verification

All commands from a clean clone of `feat/p2-evaluation-system`, after
`python -m pip install -e ".[dev]"`.

| Command | Result |
|---|---|
| `python -m ruff check .` | All checks passed |
| `python -m mypy` | Success: no issues found in 37 source files |
| `python -m pytest -q` | 231 passed |
| `git diff --check` | clean |
| `python -m pytest -q tests/evals` | 134 passed |
| `python -m agentic_rag.evals.run --dataset data/eval/golden_research.jsonl --repeat 3 --out reports/evals/latest.json` | exit 0; 12/12 invariants held; 66/66 expectations met; stable over 3 repeats |

**Clean-clone reproducibility.** Cloning the branch fresh, installing, and
re-running the exact command that produced the committed artifact regenerates
`reports/evals/latest.json` and `reports/evals/latest.md` byte for byte, ignoring
the CRLF the Windows checkout introduces.

One fix was needed to get there: the dataset digest was over the file's raw
bytes, so a Windows clone (CRLF) and a Linux clone (LF) reported different
dataset identities for the same curation. Newlines are now normalised before
digesting, and nothing else is — a changed question, a reordered line or a changed
expectation all still move it.

Artifact digests at the head of this branch:

| Artifact | Digest |
|---|---|
| `data/eval/golden_research.jsonl` | `sha256:03e6c070b2bbafb380710bbcd433e9c30d2d40d33072927b9de1b4e813f697da` |
| `reports/evals/latest.json` — `results_digest` | `sha256:0e568d5e2a5a0c7faaabfec23730fecbe01e5d35841e14e00dbffe4903fddc6b` |
| Per-pass case records (all three repeats) | `sha256:041797a5421aed721a37c683887a15192680348bc6e0f48310d5f920d561404a` |

---

## 8. Limitations and residual risks

1. **The spec model shares an author with the implementation** (§2.1). The most
   significant residual risk in the lane.
2. **The corpus is five passages.** Slice sizes are small enough that one case can
   move a per-slice rate by 7–17 percentage points. The per-slice tables state
   their denominators for exactly this reason.
3. **Expectations are derived from *current* documentation.** If a documented rule
   is itself wrong, every layer here agrees with it consistently. The evaluation
   measures conformance to a contract, not the wisdom of the contract.
4. **`surface_form_invariance` covers six axes** — case, repeated whitespace,
   trailing punctuation, hyphen versus em dash, and a non-breaking space. Unicode
   normalisation forms, combining marks and non-Latin scripts are untested; the
   tokeniser matches ASCII alphanumerics, so those questions would tokenise to
   nothing rather than misbehave, but that is reasoning, not a measurement.
5. **Determinism is measured over repeats in one process.** Cross-process and
   cross-platform stability is evidenced by the clean-clone reproduction on the
   same OS only; no CI matrix result is claimed.
6. **The single-pass reference is not the comparison the architecture describes.**
   That one pairs the agent against production-RAG answering directly and needs
   the live path, which is out of this lane's scope.
7. **`degraded` is unreachable** and is therefore absent from the schema. When a
   backend that can degrade exists, the schema and this document need a new slice.
