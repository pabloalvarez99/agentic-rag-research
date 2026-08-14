# ADR-0002 — The step budget lives in the state, and two independent bounds end every run

- **Status:** accepted
- **Date:** 2026-08-13
- **Scope:** termination of the research loop, where the budget is enforced, and what a
  run is allowed to report about why it stopped

## Context

An agent loop decides at runtime how much work it does. That is the whole reason to
build one, and it is also the failure mode: a loop whose stop rule is wrong does not
return a wrong answer, it returns nothing at all while spending a retrieval call per
iteration until something times out. On a hosted provider that is a bill; on the free
path it is a hung test.

The obvious implementation is the one almost every agent tutorial ships:

```python
while steps < max_steps and not done:
    ...
    steps += 1
```

It has two defects that only show up once the loop has more than one exit. The counter
is incremented by whoever wrote the loop, so a second call site — a retry, a fan-out, a
recovery path added later — is a second place that has to remember. And the bound is a
property of the loop's condition rather than of the run, so a run that stopped early
and a run that was cut off are indistinguishable afterwards unless someone also
remembered to record which happened.

The second defect matters more than the first. `budget_exhausted` is the first field an
operator checks when asked why a report was thin. If it can be set by a run that stopped
for an unrelated reason, the field is worse than absent: it sends the reader to the
wrong question.

There is also a bound nobody writes down. A critic that names a gap no retrieval can
close will name it again next iteration, and the loop will re-issue the same
sub-question, receive the same passages, and burn the budget. The run then reports
`budget_exhausted` — truthfully, and completely misleadingly, because what actually
happened is that the loop stopped making progress on step two.

## Decision

**Termination does not depend on the critic being right. Two independent bounds
guarantee it, and the budget is enforced by the state rather than by the loop.**

1. **`ResearchState.record_retrieval` raises `StepBudgetExceeded` when the budget is
   spent.** The budget is a property of the run, checked in the one method that spends
   it. A caller cannot spend a step without going through it, so there is no second call
   site to keep in step. It raises rather than silently dropping the step, because a run
   that quietly stops recording still looks complete in its trace, and the missing work
   is visible only to someone who thinks to compare step counts.
2. **No sub-question is retrieved for twice.** Every follow-up a critique proposes is
   checked against everything already requested and everything already queued, so the
   pending queue strictly shrinks. A run can therefore end with steps left over — which
   is a real outcome and gets its own reason rather than being rounded up to the budget.
3. **The stop reason comes from a closed set, decided by a pure function.**
   `decide_outcome(sufficient, has_evidence, budget_spent)` in `agent/graph.py` maps
   three booleans onto a status and a reason. The order of those tests *is* the policy,
   so the policy is one readable function rather than a sequence of `if` statements
   scattered through a loop body where it can be quietly reordered.
4. **A run that gathered thin evidence and still has steps left refuses with
   `insufficient_evidence`, never with `budget_spent`.** The status field is not allowed
   to flatter or to misdirect.
5. **`top_k` is the second budget, per step rather than per run.** It caps the evidence
   one retrieval may return. It is separate from `max_steps` because they bound
   different costs: steps bound calls to the retrieval service, `top_k` bounds the
   context one call drags back.
6. **The defaults are `max_steps=4` and `top_k=5`,** and they are constants with names
   (`DEFAULT_MAX_STEPS`, `DEFAULT_TOP_K`) rather than literals at a call site.

### The resulting outcome table

| `sufficient` | `has_evidence` | `budget_spent` | Status | Reason |
| --- | --- | --- | --- | --- |
| yes | — | — | `done` | `evidence_sufficient` |
| no | no | — | `refused` | `no_evidence` |
| no | yes | yes | `budget_exhausted` | `budget_spent` |
| no | yes | no | `refused` | `insufficient_evidence` |

Sufficient evidence answers whatever the budget did — a run that reached its last step
and *then* found what it needed has succeeded, and reporting the budget would be an
apology for a correct run.

## What this does not decide

**Wall-clock and spend budgets are not implemented.** `max_steps` bounds the number of
retrieval calls, which on the free path is the only cost there is: the fake backend
contacts nothing and bills nothing, and a run finishes in milliseconds. A timeout would
be dead code, and a spend ceiling would be a field that always reads zero.

They are the right bounds the moment the HTTP backend runs against a real instance, and
that is when they land — with the failure mode they exist to survive in front of them,
rather than guessed at now. The seam is the same one the step budget uses: a `record_*`
method on the state that can refuse.

**Per-sub-question budgets stay open.** Today a run has one budget spent by whichever
sub-question comes first. Whether a plan of three sub-questions should be able to spend
its whole budget on the first one is a real question with no evidence behind either
answer yet.

## Alternatives considered

**A counter in the loop, incremented at the call site.** The tutorial version, and by
far the least code. Rejected because it makes the bound a property of one loop rather
than of the run: the second call site that spends a step is where it silently breaks,
and the failure is invisible — a run that overspends still produces a complete-looking
trace. The state-enforced version costs one method and makes overspending raise on the
line that did it.

**A wall-clock timeout as the primary bound.** Attractive because it bounds the thing
that actually hurts in production — latency — regardless of what the loop does per step.
Rejected as the primary bound because it makes the free path non-deterministic: the same
question on a slower machine takes a different number of steps, so two runs of the same
question produce different traces and no test can assert on one. Determinism is what
makes the loop testable at this milestone. A timeout returns as a secondary bound with
the hosted path, where it bounds a cost that exists.

**Let the critic alone decide when to stop.** The most agent-like design: no ceiling,
just a judgement about sufficiency. Rejected on the grounds that this is precisely the
component most likely to be wrong, and later most likely to be a model. A stop rule that
depends on the judgement it is meant to bound is not a bound. The critic decides when a
run *may* stop early; it cannot decide that a run continues.

**Re-issue a sub-question when the critique still names its gap.** The natural reading
of "the gap is still open, try again". Rejected: the fake backend is deterministic, so
an identical request returns an identical result, and even a real service would return
near-identical results within one run. It converts every unclosable gap into
`budget_exhausted`, which destroys the distinction between "ran out of room" and
"stopped making progress" — the one distinction the stop reason exists to carry.

**Cap the plan instead of the run.** The planner already caps at three sub-questions, so
a plan cannot outrun a budget of four. Rejected as *the* bound because it only bounds
the plan, and critiques add follow-ups the planner never proposed. The cap stays as a
sanity rule on the planner; it is not what guarantees termination.

## Consequences

**Bought.** Termination is guaranteed by construction rather than by the critic being
correct, which matters most in the future where the critic is a model. `budget_exhausted`
means exactly one thing, so it is worth putting in a report. A run that stops early is
distinguishable from a run that was cut off, which is the difference between "the corpus
does not cover this" and "give it more room". Overspending raises at the line that did
it instead of surfacing as an accounting discrepancy later.

**Accepted costs.** The budget lives somewhere less obvious than the loop that appears to
spend it, so reading `run_research` alone does not show where the ceiling is enforced —
paid back the first time a second call site appears. `StepBudgetExceeded` is an
exception on a path that, today, no correct caller can reach; it exists for the callers
that do not exist yet. And the no-repeat rule means a genuinely useful retry with
identical wording is refused: a narrower re-framing is a different sub-question and is
allowed, but the loop cannot simply ask again.

**Checkable.** `tests/test_research_state.py` covers the raise at the boundary;
`tests/test_research_loop.py` covers each row of the outcome table. The budget-stress
cases in [`data/eval/golden_research.jsonl`](../../data/eval/golden_research.jsonl) pair
identical questions at different budgets, so the only variable between a `done` and a
`budget_exhausted` run is the ceiling itself.
