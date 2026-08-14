# Agent loops

## Planning before acting

An agent plans by turning a question into the sub-questions it would have to answer, then spends one step on each. The plan is written into the run before any tool is called, so a reviewer can compare what the agent intended to do against what it actually did.

## Step budgets

Every loop carries a hard step budget. A loop that stops only when a critic is satisfied has no upper bound on cost, because the condition that ends it is produced by the same system being measured. Exhausting the budget is a terminal state with its own name and is reported rather than smoothed over.

## Tools and their errors

A tool failure is not the same as a tool finding nothing. An unreachable backend unwinds the step and degrades the run; an empty result is evidence about the corpus and the loop reasons about it. Collapsing the two teaches the agent that an outage means the answer does not exist.

## Traces

A trace records one event per decision — plan created, tool called, tool result, critique, synthesis, stop — with the payload that decision was made from. It is the artifact that makes an agent auditable instead of anecdotal, and it costs nothing to keep on the free path.
