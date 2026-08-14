# Hybrid retrieval

## Hybrid search

Hybrid retrieval runs a dense vector search and a sparse keyword search over the same corpus and fuses the two rankings with reciprocal rank fusion, so a query that only one of them understands still returns evidence.

## Reciprocal rank fusion

Reciprocal rank fusion scores a document by the sum of `1 / (k + rank)` across the rankings it appears in, with k around sixty. It combines rankings rather than scores, which is the point: a dense similarity and a lexical weight are not measured on the same scale and calibrating them against each other is a tuning job that never finishes.

## When each branch fails

A dense search matches paraphrase and misses rare tokens such as identifiers, version strings and product names. A lexical search does the opposite. Fusing them is worthwhile precisely because their failures do not overlap; running two searches that fail on the same inputs would only cost twice as much.
