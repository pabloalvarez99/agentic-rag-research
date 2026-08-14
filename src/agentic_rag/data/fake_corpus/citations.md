# Citations

## Citation markers

Every citation marker in an answer resolves to a chunk that was actually retrieved. A marker resolving to nothing is dropped and reported, because a citation nobody can follow is decoration.

## Markers bind to the prompt

A marker is resolved against the ordered blocks that were placed in the prompt, never against the raw retrieval result. The two lists differ whenever context was truncated, and resolving against the wrong one silently attributes a sentence to a passage the model never saw.

## Invalid markers as a signal

The count of dropped markers is worth recording per run. It measures how often generation reaches past its evidence, and unlike a quality judge it costs nothing and needs no second model to compute.
