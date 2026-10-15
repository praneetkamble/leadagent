"""The agent pipeline. State lives in a persisted Run, so the human-approval pause survives a process restart.

ingest -> extract facts -> score fit (rubric) -> draft pitch -> verify (grounding) -> PAUSE -> human approve / edit / reject
"""
from __future__ import annotations
import json
import time
import uuid
from datetime import datetime, timezone

from . import config, llm, pitch
from .extract import extract_facts, facts_digest
from .ingest import load_source, parse_html
from .score import score_fit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunStore:
    def __init__(self, root=None):
        self.root = (root or config.DATA_DIR) / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.outbox = (root or config.DATA_DIR) / "outbox"

    def save(self, run: dict):
        (self.root / f"{run['id']}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))

    def get(self, rid: str) -> dict:
        p = self.root / f"{rid}.json"
        if not rid.isalnum() or not p.exists():
            raise KeyError(rid)
        return json.loads(p.read_text())

    def list(self) -> list[dict]:
        runs = [json.loads(p.read_text()) for p in self.root.glob("*.json")]
        runs.sort(key=lambda r: r["created"], reverse=True)
        return [{k: r[k] for k in ("id", "created", "source", "status", "business", "score", "tier")} for r in runs]


class Tracer:
    def __init__(self, run): self.run = run
    def step(self, name, mode, fn, summary_in=""):
        t = time.perf_counter()
        try:
            out, summary = fn()
            status = "ok"
        except Exception as e:                                  # recorded, then re-raised
            self.run["trace"].append({"step": name, "mode": mode, "ts": _now(), "ms": round((time.perf_counter() - t) * 1000, 1),
                                      "status": "error", "input": summary_in, "summary": str(e)})
            raise
        self.run["trace"].append({"step": name, "mode": mode, "ts": _now(), "ms": round((time.perf_counter() - t) * 1000, 1),
                                  "status": status, "input": summary_in, "summary": summary})
        return out
    def note(self, name, mode, summary):
        self.run["trace"].append({"step": name, "mode": mode, "ts": _now(), "ms": 0, "status": "ok", "input": "", "summary": summary})


def start_run(source: str, store: RunStore, force_draft: bool = False, llm_client=None) -> dict:
    run = {"id": uuid.uuid4().hex[:10], "created": _now(), "source": "", "status": "running", "trace": [],
           "business": None, "score": None, "tier": None, "facts": None, "fit": None, "draft": None, "grounding": None,
           "draft_history": [], "decision": None, "llm": llm.enabled()}
    tr = Tracer(run)
    try:
        raw, label = tr.step("1_ingest", "rule", lambda: _ingest(source), summary_in=source[:80])
        run["source"] = label
        doc = tr.step("1b_parse", "rule", lambda: (lambda d: (d, f"title='{d['title']}', {len(d['text'].split())} words, {len(d['links'])} links"))(parse_html(raw)))
        F = tr.step("2_extract_facts", "rule", lambda: (lambda f: (f, f"{len(f)} facts; type={f['business_type']['value']}, city={f['city']['value']}"))(extract_facts(doc)))
        run["facts"] = F; run["business"] = F["business_name"]["value"]
        fit = tr.step("3_score_fit", "rule", lambda: (lambda s: (s, f"score {s['score']}/100 ({s['tier']})" + (" [capped: chain]" if s['capped_for_chain'] else "")))(score_fit(F)))
        run["fit"] = fit; run["score"] = fit["score"]; run["tier"] = fit["tier"]
        if fit["score"] < config.MIN_FIT_TO_DRAFT and not force_draft:
            tr.note("4_decision", "rule", f"Score {fit['score']} < {config.MIN_FIT_TO_DRAFT}: not a good fit, no pitch drafted. (Re-run with force_draft to override.)")
            run["status"] = "skipped_low_fit"
        else:
            draft = tr.step("4_draft_pitch", "llm" if llm.enabled() else "rule", lambda: _draft(F, fit, llm_client, tr))
            run["draft"] = draft
            g = tr.step("5_verify_grounding", "rule", lambda: (lambda g: (g, "passed" if g["passed"] else "FAILED: " + "; ".join(g["problems"])))(pitch.grounding_check(draft, F, doc["text"])))
            run["grounding"] = g
            run["_site_text"] = doc["text"]
            run["status"] = "awaiting_approval"
            tr.note("6_human_gate", "human", "PAUSED. Nothing is sent. Waiting for a human to approve, edit or reject this draft.")
    except Exception as e:
        run["status"] = "error"; run["error"] = str(e)
    store.save(run)
    return run


def _ingest(source):
    raw, label = load_source(source)
    return (raw, label), f"loaded {len(raw)} chars from {label}"


def _draft(F, fit, client, tr):
    if llm.enabled():
        try:
            d = pitch.llm_pitch(F, fit, client)
            return d, "LLM draft: " + d["subject"]
        except llm.LLMError as e:
            tr.note("4_draft_pitch", "rule", f"LLM failed ({e}); using deterministic template instead")
    d = pitch.template_pitch(F, fit)
    return d, "template draft: " + d["subject"]


def decide(store: RunStore, rid: str, action: str, subject: str | None = None, body: str | None = None, reason: str = "") -> dict:
    run = store.get(rid)
    tr = Tracer(run)
    if run["status"] != "awaiting_approval":
        raise ValueError(f"Run is '{run['status']}', not awaiting approval.")
    if action == "edit":
        run["draft_history"].append(run["draft"])
        run["draft"] = {"subject": subject or run["draft"]["subject"], "body": body or run["draft"]["body"]}
        run["grounding"] = pitch.grounding_check(run["draft"], run["facts"], run["_site_text"])
        tr.note("7_human_edit", "human", "Draft edited. Re-verified: " + ("passed" if run["grounding"]["passed"] else "FAILED: " + "; ".join(run["grounding"]["problems"])))
    elif action == "approve":
        if not run["grounding"]["passed"]:
            raise ValueError("Cannot approve: draft fails the grounding check. Edit it first.")
        run["status"] = "approved"; run["decision"] = {"action": "approve", "ts": _now()}
        store.outbox.mkdir(parents=True, exist_ok=True)
        (store.outbox / f"{rid}.txt").write_text(f"Subject: {run['draft']['subject']}\n\n{run['draft']['body']}\n")
        tr.note("7_human_approve", "human", f"Approved. Saved to outbox/{rid}.txt for you to send manually. LeadAgent never sends email.")
    elif action == "reject":
        run["status"] = "rejected"; run["decision"] = {"action": "reject", "reason": reason, "ts": _now()}
        tr.note("7_human_reject", "human", "Rejected" + (f": {reason}" if reason else ""))
    else:
        raise ValueError("action must be approve, edit or reject")
    store.save(run)
    return run


def public(run: dict) -> dict:
    return {k: v for k, v in run.items() if not k.startswith("_")}
