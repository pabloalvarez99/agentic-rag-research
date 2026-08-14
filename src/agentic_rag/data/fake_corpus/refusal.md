# Refusal

## Refusal as an outcome

Refusal is a first-class outcome. When the retrieved evidence does not support an answer the pipeline says so and names the gap, instead of padding thin evidence with parametric memory.

## Naming the reason

A refusal carries a stable reason slug rather than prose. `no_evidence` means retrieval came back empty or too thin to support a claim; `budget_exhausted` means an agent ran out of steps with the question still open. Reading the two as the same event hides which half of the system needs work.

## Detecting abstention

Abstention is detected by a constant sentinel the provider is instructed to emit, never by pattern matching the prose. A model that happens to begin an answer with an apology is not abstaining, and a model that abstains politely would otherwise be scored as an answer.
