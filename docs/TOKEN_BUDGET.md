# Token & Cost Budget Policy

## Principle
LLM is expensive. Use it only where language generation/reasoning adds clear value.

## No-LLM zones (v0.x)
- ingestion (HH/TG)
- deduplication
- heuristic scoring
- policy decisions and counters
- dashboards aggregation

## LLM allowed (later, gated)
- cover letters for score > 7 only
- weekly market/cv gap analysis on aggregated/sampled data
- strict caching, minimal context, daily caps

## Engineering rules
- 1 PR = 1 small change
- no full-file rewrites
- tests & fixtures early to avoid “re-discussing” behavior
