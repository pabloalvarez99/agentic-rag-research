# DEMO-DAY — 15 minutes on pax-agentic-rag (v1.0)

**Host only:** https://pax-agentic-rag.vercel.app  
**Project only:** `pax-agentic-rag` (never promote the sibling Vercel project)  
**Claim:** control / mechanism demo, fixture retriever, **$0**, no live-web research.

| Min | Beat |
| ---: | --- |
| 0–1 | Open `/`, health, honesty copy (fake path, no API key). |
| 1–4 | **Refuse.** Off-corpus question (Patagonia revenues / Antarctic chess). Status refused, gaps named. Download full `run.json` immediately. |
| 4–6 | **Critic can lose.** Tell the story of notes present but off-topic ≠ success; point at golden `critic-notes-exist-not-success` and ADR-0004. |
| 6–9 | **Done control.** Default form question or RRF question. Citations, trace offsets. Download second run. |
| 9–11 | **`/compare`.** Load both JSON files. Typed diffs on status/stop/steps/notes — payloads, not ids (ADR-0005). Recycle story. |
| 11–13 | **`/pack`.** Build experiment pack from the two files; show `pack_hash` and compare block. |
| 13–15 | **Load honesty + close.** Show `docs/assets/load.json` p50/p95 (single process, not capacity). What is still PLANNED. Optional `hosted_smoke.ps1`. |

## curl cheat sheet

```bash
BASE=https://pax-agentic-rag.vercel.app
curl -sS "$BASE/health"
curl -sS -X POST "$BASE/v1/research" -H "content-type: application/json" \
  -H "x-request-id: demo-refused" \
  -d '{"question":"What were the quarterly revenues in Patagonia?","max_steps":3,"retriever":"fake"}'
curl -sS -OJ "$BASE/v1/runs/demo-refused/run.json"
```

## Non-goals during the demo

- Do not open `production-rag.vercel.app` (Ipsura).
- Do not claim live web research or answer quality SOTA.
- Do not depend on an id after a cold start — use the downloaded file.
