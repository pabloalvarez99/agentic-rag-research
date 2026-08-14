# Reranking

## Cross-encoder reordering

A cross-encoder reranker reads the query and a candidate passage together and reorders the shortlist. It costs far more per pair than the retriever, which is why it runs over tens of candidates instead of the whole index.

## Failing open

When the reranker is unavailable the pipeline keeps the fused order and records that the stage was skipped. Losing precision is recoverable; losing the answer is not. A capability that was requested and cannot be served at all, such as hybrid mode over an index with no sparse vectors, is the opposite case and fails loudly instead.
