# Multi-hop questions

## One search is not always enough

A multi-hop question needs a fact that no single passage carries. Asking it verbatim retrieves passages that match its wording and none that carry the bridge between its parts, so the run looks successful while the evidence answers a different question.

## Decomposition

Decomposing a compound question into narrower sub-questions changes the terms being searched, and different terms reach different passages. That is the mechanism behind an iterative loop: not more attempts at the same query, but a different query each step.

## Knowing when to stop

A critic decides whether the evidence gathered so far covers the question, and names the uncovered terms as gaps when it does not. Those gaps are what the next step searches for, which is why a critic that only returns a score is not enough to drive another round.
