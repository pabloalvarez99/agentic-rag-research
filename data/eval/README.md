# Golden dataset — `golden_research.jsonl`

66 questions for the research loop, hand-written in this repository against the
20-passage packaged Markdown fixture exposed as
`agentic_rag.tools.retrieve.DEFAULT_CORPUS`.

The file is the input to `python -m agentic_rag.evals.run`. Its schema, and every
integrity rule below, live in `agentic_rag.evals.dataset`.

## Provenance and licence

| | |
|---|---|
| Origin | Written for this repository. No external dataset, benchmark or corpus was copied, adapted or scraped. |
| Licence | MIT, the repository's licence. There is no third-party licence to honour because there is no third-party content. |
| Model involvement | The questions and the expectations were composed by hand and cross-checked against a re-derivation of the documented rules. No answer, report or trace produced by the system was copied into the file. |
| Subject matter | The fixture's own subject: hybrid retrieval, reranking, citations, refusal, chunking, bounded agent loops, and multi-hop research. Plus deliberately off-subject questions, which are the point of the refusal slice. |
| Personal data | None. No question names a person, and the corpus is 20 passages of technical prose committed with the repository. |

## What a case may and may not say

A case declares **constraints on how a run must behave**. It cannot declare what
the answer says, and the schema gives it nowhere to try: `EvalCase` forbids
unknown fields and has no field for a report, an answer or a snippet.

That is the leakage rule made structural. An expectation is derived from a rule
that is written down — the planner's split, the critic's threshold, the outcome
table in `docs/architecture.md`, the contents of the fixture corpus — and every
case carries a `rationale` stating which rule it was derived from. An expectation
that can only be justified by "that is what the code printed" does not belong in
the file, and a reviewer can check that by reading the rationale against the doc.

| Field | Meaning |
|---|---|
| `id` | Stable kebab-case identifier. Never reused for a different question. |
| `category` | One of the six behaviour slices below. |
| `question` | What the loop is asked. Unique across the file, before and after whitespace normalisation, unless the case belongs to a `normalization_group`. |
| `max_steps`, `top_k` | The two bounds the run is given. |
| `expected_terminal_status` | `done`, `refused` or `budget_exhausted`. |
| `expected_stop_reason` | Must be a reason that status can carry. |
| `expected_min_citations`, `expected_max_citations` | Bounds on distinct citations. `null` for no upper bound. |
| `expected_source_paths`, `expected_chunk_ids` | Provenance that must appear. Checked to exist in the corpus. |
| `expected_min_plan_size` | Floor on planned sub-questions, from the planner's documented split rule. |
| `expects_repeated_evidence` | Whether two steps should retrieve the same passage. |
| `normalization_group` | Ties surface-form variants of one question together. |
| `rationale` | Why this expectation follows from a documented rule. |

## The six slices

| Slice | Cases | What it is for |
|---|---|---|
| `single_source_answerable` | 14 | One passage answers the question. Pins the ordinary path: retrieve once, clear the sufficiency threshold, cite one passage. |
| `multi_concept` | 12 | Compound questions the planner splits. Includes three whose first sub-question is deliberately off-corpus, so the loop must reach the second one to answer at all. |
| `no_evidence_refusal` | 14 | 8 questions no passage touches, which must refuse with `no_evidence`; and 6 that retrieve something too thin to be sufficient, which must refuse with `insufficient_evidence` while budget remains. The pair matters: a run that blames the budget for a shortage of evidence is wrong even though it also stopped. |
| `budget_pressure_partial` | 8 | Budgets too small for the evidence. Must report a partial answer and say the budget ended it. |
| `duplicate_evidence` | 6 | Both sub-questions retrieve the same passage. Two steps of evidence must remain one citation. |
| `text_normalization` | 12 | Six pairs differing only in case, whitespace, punctuation, dash or a non-breaking space. Both members must behave identically, on the refusal path as well as the answering one. |

Six pairs is 12 cases because a normalisation claim needs two surface forms to
compare; the group is the unit, not the case.

### Why the multi-concept slice looks the way it does

The critic scores gathered evidence against the whole question rather than only
the current sub-question. A passage that covers the compound question can satisfy
the run immediately, so the slice's primary expectation is about the **plan**, not
a forced step count: `expected_min_plan_size` of 2 asserts that the planner split
the question. Cases whose first sub-question is deliberately off-corpus force the
loop to walk the plan and catch an implementation that plans but ignores it.

That asymmetry is a finding about the loop, recorded here rather than smoothed over.

## Integrity rules

`validate_dataset` refuses the file — the run exits `3` and evaluates nothing —
when any of these fail:

- an `id` is duplicated, or is not kebab-case
- a `question` is duplicated, or duplicates another after whitespace normalisation
  while belonging to a different `normalization_group`
- a `schema_version` does not match the loader's
- a status carries a reason it cannot carry, e.g. `done` with `no_evidence`
- `expected_min_citations` exceeds `expected_max_citations`, or exceeds
  `max_steps × top_k`, which no run could reach
- a `no_evidence` case expects citations or provenance
- a case expecting repeated evidence has fewer than two steps of budget
- a question below the planner's short-question threshold expects a plan larger
  than one, or any case expects a plan larger than its budget
- a `chunk_id` or `source_path` is not in the corpus, or the two disagree
- a slice obligation is unmet, e.g. a `single_source_answerable` case naming two
  source paths
- a `normalization_group` has fewer than two members, or its members expect
  different outcomes
- the file holds fewer than 48 cases, or a slice is empty

The last rule is the one that matters for honesty: the floor is checked on every
run, so a dataset cannot be quietly shrunk to the cases that pass.

## Changing the file

1. Add the case with its `rationale`, stating the documented rule it follows from.
2. Run `python -m agentic_rag.evals.run --dataset data/eval/golden_research.jsonl --validate-only`.
3. Run the suite: `python -m pytest -q tests/evals`. `tests/evals/test_golden_dataset.py`
   re-derives every expectation from an independent model of the documented rules,
   so a case justified only by what the implementation printed fails there.
4. Regenerate the artifact and commit it alongside the change.

Never edit an expectation because a run disagreed with it. A disagreement means
either the rule changed, the loop regressed, or the expectation was wrong — and
which one it is has to be decided before the file moves.

The current cases were re-derived against the 20-passage corpus after M3 landed.
`single_source_answerable` cases use `top_k=1` so their one-source contract remains
meaningful as the corpus grows. The runner records a dataset digest in every
scorecard, making a result inseparable from the exact JSONL it evaluated.
