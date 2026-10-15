# LeadAgent — multi-step lead-qualification agent with human approval

Takes a business website (saved sample page, pasted text/HTML, or an opt-in public URL) and runs a transparent pipeline:

```
ingest → extract facts (with evidence) → score fit (rubric) → draft pitch → grounding check → ⏸ PAUSE → human approve / edit / reject
```

Every step is written to a trace log, and the run is persisted to disk, so the pause survives a restart.
**LeadAgent never sends anything.** "Approve" only saves the final text to `data/outbox/<id>.txt` for a person to send.

> **Status:** working demo built as a portfolio project. The GitHub repo `praneetkamble/leadagent`
> **has not been created yet**; this folder is the source. Nothing is deployed.

## What is actually used

| Step | Implementation |
|---|---|
| Ingest | stdlib HTML parser over 6 **fictional** saved websites in `fixtures/` (no scraping). Live URL fetch is **off** unless `LEADAGENT_ALLOW_FETCH=1`, only public http(s) hosts (private/loopback blocked) |
| Extract facts | **rule-based** (regex + keywords): business type, city, phone/email/WhatsApp, mobile viewport tag, copyright year, placeholder text, online ordering/booking, Google Maps link, menu as PDF/photo, chain/franchise… each fact keeps its evidence snippet |
| Score fit | **rule-based, 100-point rubric** (`leadagent/score.py`), no LLM so every point is traceable. Chains/franchises are capped at 20. Below 40 → no pitch is drafted (override with "Draft even if fit is weak") |
| Draft pitch | deterministic **template** by default. Optional LLM (`LEADAGENT_LLM_BASE_URL`, `LEADAGENT_LLM_MODEL`, `LEADAGENT_LLM_API_KEY`, any OpenAI-compatible endpoint); on any LLM error it falls back to the template |
| Verify | **grounding check**: every number and URL in the draft must exist in the site text / seller profile; flags guarantee/urgency wording; must mention the business name. A draft that fails cannot be approved until edited |
| Human gate | approve / edit (re-verified) / reject (with reason) |
| UI | FastAPI + plain JS dashboard: rubric bars with evidence, trace timeline, editable draft |

Seller details used in the pitch live in `profile.json` (name, portfolio link, services). **Edit it before real use.**
The LLM path is tested with a *mocked* endpoint only; I have not run it against a real model. The default (and everything measured here) is rule-based.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
uvicorn leadagent.api:app --port 8001        # dashboard at http://localhost:8001
python -m leadagent run brew_bloom_cafe       # or from the CLI
python -m leadagent decide <run-id> approve   # approve | reject --reason "..." | edit --body "..."
```

Docker: `docker build -t leadagent . && docker run -p 8001:8001 -v $PWD/data:/data leadagent` (Dockerfile written, **not built here: Docker isn't installed on my machine**).

## Rubric results on the 6 fixtures (just the rubric's output, not an accuracy claim)

| Fixture (fictional) | Score | Tier | Why |
|---|---|---|---|
| sharma_sweets | 95 | strong | under-construction page, no mobile layout, © 2012, no ordering, no Maps |
| brew_bloom_cafe | 90 | strong | no mobile layout, © 2017, PDF menu, no ordering, no Maps |
| spice_route_kitchen | 75 | strong | mobile OK, but © 2021, menu is a photo, no online ordering, no Maps |
| glow_studio_salon | 60 | moderate | no online booking, no Maps |
| lotus_dental_care | 35 | weak (skipped) | modern site with booking, Maps and reviews |
| urbanbite_franchise | 20 | weak (skipped) | 64-outlet chain, capped |

## Limitations

- The rubric weights are my own judgement, not learned from data; I have **no evidence** about reply or conversion rates.
- Extraction is regex-based and tuned to the 6 fixtures; real sites (JS-rendered, multi-page, other languages) will need more work.
- The template pitch is generic by design; an LLM may write better text but the grounding check is only a lightweight guard, not a fact-checker.
- Single user, no auth, JSON files for storage.

## Tests

```bash
pip install -r requirements-dev.txt && python -m pytest -q    # 19 tests: extraction, rubric, pipeline trace, pause/restart, approve/edit/reject, grounding, mocked LLM + fallback, URL safety, API
```
