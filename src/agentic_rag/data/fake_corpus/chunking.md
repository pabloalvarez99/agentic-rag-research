# Ingest

## Chunking

Chunking splits a document on its heading structure before it splits on size, so a chunk carries the heading path it came from and a retrieved passage can be traced back to its place in the source.

## Stable identity

A chunk keeps a stable identifier derived from its source and its position, so re-running ingest over an unchanged document upserts the same records instead of duplicating them. Content hashes make the unchanged case cheap to detect.
