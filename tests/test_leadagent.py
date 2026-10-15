import json
import pytest
from fastapi.testclient import TestClient

from leadagent import config, llm, pipeline, pitch
from leadagent.extract import extract_facts
from leadagent.ingest import load_source, parse_html, fetch_url
from leadagent.pipeline import decide, start_run
from leadagent.score import RUBRIC, score_fit


def facts(name):
    raw, _ = load_source(name)
    return extract_facts(parse_html(raw))


# ---------- extraction
def test_extracts_outdated_cafe_facts():
    F = facts("brew_bloom_cafe")
    assert F["business_name"]["value"] == "Brew & Bloom Cafe"
    assert F["business_type"]["value"] == "cafe" and F["city"]["value"] == "Pune"
    assert F["has_viewport_meta"]["value"] is False
    assert F["copyright_year"]["value"] == 2017
    assert F["has_online_ordering"]["value"] is False and F["menu_is_pdf_or_image"]["value"] is True
    assert F["has_phone"]["value"] is True and F["site_builder_hint"]["value"] == "Wix"


def test_extracts_modern_clinic_and_chain():
    c = facts("lotus_dental_care")
    assert c["has_online_booking"]["value"] and c["has_viewport_meta"]["value"] and c["has_google_maps_link"]["value"]
    u = facts("urbanbite_franchise")
    assert u["is_franchise_or_chain"]["value"] and u["outlet_count"]["value"] == 64


def test_no_online_booking_phrase_is_negative():
    assert facts("glow_studio_salon")["has_online_booking"]["value"] is False


# ---------- scoring
def test_rubric_sums_to_100_and_scores_are_deterministic():
    assert sum(r[1] for r in RUBRIC) == 100
    F = facts("brew_bloom_cafe")
    a, b = score_fit(F), score_fit(F)
    assert a == b and a["score"] == sum(i["earned"] for i in a["items"]) == 90


def test_expected_ordering_of_fixtures():
    s = {n: score_fit(facts(n))["score"] for n in
         ["sharma_sweets", "brew_bloom_cafe", "spice_route_kitchen", "glow_studio_salon", "lotus_dental_care", "urbanbite_franchise"]}
    assert s["sharma_sweets"] > s["brew_bloom_cafe"] > s["spice_route_kitchen"] > s["glow_studio_salon"] > s["lotus_dental_care"] > s["urbanbite_franchise"]
    assert score_fit(facts("urbanbite_franchise"))["capped_for_chain"]


# ---------- pipeline + human gate
def test_pipeline_pauses_for_approval_and_traces_steps(store):
    run = start_run("brew_bloom_cafe", store)
    assert run["status"] == "awaiting_approval"
    steps = [t["step"] for t in run["trace"]]
    assert steps == ["1_ingest", "1b_parse", "2_extract_facts", "3_score_fit", "4_draft_pitch", "5_verify_grounding", "6_human_gate"]
    assert run["draft"] and run["grounding"]["passed"]
    assert not (store.outbox / f"{run['id']}.txt").exists()          # nothing "sent" before approval


def test_pause_survives_restart(store, tmp_path):
    rid = start_run("sharma_sweets", store)["id"]
    again = pipeline.RunStore(tmp_path)                               # new process/object, same disk
    assert again.get(rid)["status"] == "awaiting_approval"


def test_approve_writes_outbox_but_never_sends(store):
    rid = start_run("brew_bloom_cafe", store)["id"]
    run = decide(store, rid, "approve")
    assert run["status"] == "approved"
    assert "Subject:" in (store.outbox / f"{rid}.txt").read_text()
    with pytest.raises(ValueError):
        decide(store, rid, "approve")                                 # already decided


def test_reject_records_reason(store):
    rid = start_run("brew_bloom_cafe", store)["id"]
    run = decide(store, rid, "reject", reason="not my area")
    assert run["status"] == "rejected" and run["decision"]["reason"] == "not my area"
    assert not store.outbox.exists() or not list(store.outbox.glob("*.txt"))


def test_edit_is_reverified_and_bad_edit_blocks_approval(store):
    rid = start_run("brew_bloom_cafe", store)["id"]
    run = decide(store, rid, "edit", body="Hi Brew & Bloom Cafe, we guarantee 300% more orders. See https://evil.example")
    assert run["status"] == "awaiting_approval" and not run["grounding"]["passed"]
    assert len(run["draft_history"]) == 1
    with pytest.raises(ValueError, match="grounding"):
        decide(store, rid, "approve")
    good = decide(store, rid, "edit", body="Hi Brew & Bloom Cafe team, I can build you a mobile-friendly site: https://m-10-nu.vercel.app")
    assert good["grounding"]["passed"]
    assert decide(store, rid, "approve")["status"] == "approved"


def test_low_fit_is_skipped_unless_forced(store):
    r = start_run("lotus_dental_care", store)
    assert r["status"] == "skipped_low_fit" and r["draft"] is None
    f = start_run("lotus_dental_care", store, force_draft=True)
    assert f["status"] == "awaiting_approval" and f["draft"]


def test_unknown_source_is_an_error_run(store):
    r = start_run("no_such_fixture", store)
    assert r["status"] == "error" and "No fixture" in r["error"]


# ---------- grounding
def test_grounding_flags_invented_number_and_url():
    F = facts("brew_bloom_cafe")
    g = pitch.grounding_check({"subject": "Hi", "body": "Brew & Bloom Cafe will get 47 more customers, see http://x.example"}, F, "site text 2017")
    assert not g["passed"] and any("47" in p for p in g["problems"]) and any("URL" in p for p in g["problems"])


# ---------- pluggable LLM
class FakeResp:
    def __init__(self, c): self.c = c
    def raise_for_status(self): pass
    def json(self): return {"choices": [{"message": {"content": self.c}}]}


class FakeClient:
    def __init__(self, content): self.content = content
    def post(self, url, json=None, headers=None): return FakeResp(self.content)


def test_llm_draft_used_when_enabled_and_still_grounded(store, monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://x/v1"); monkeypatch.setattr(config, "LLM_MODEL", "m")
    out = json.dumps({"subject": "Idea for Brew & Bloom Cafe", "body": "Hi Brew & Bloom Cafe, your site lacks a mobile layout. Portfolio: https://m-10-nu.vercel.app"})
    r = start_run("brew_bloom_cafe", store, llm_client=FakeClient(out))        # mocked LLM, not a real model
    assert r["trace"][4]["mode"] == "llm" and r["draft"]["subject"].startswith("Idea for") and r["grounding"]["passed"]


def test_llm_garbage_falls_back_to_template(store, monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://x/v1"); monkeypatch.setattr(config, "LLM_MODEL", "m")
    r = start_run("brew_bloom_cafe", store, llm_client=FakeClient("not json at all"))
    assert r["status"] == "awaiting_approval" and r["draft"]["subject"] == "Quick idea for Brew & Bloom Cafe"
    assert any("LLM failed" in t["summary"] for t in r["trace"])


def test_llm_hallucinated_number_is_caught(store, monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://x/v1"); monkeypatch.setattr(config, "LLM_MODEL", "m")
    out = json.dumps({"subject": "Brew & Bloom Cafe", "body": "Brew & Bloom Cafe, 200 cafes grew 3x with me"})
    r = start_run("brew_bloom_cafe", store, llm_client=FakeClient(out))
    assert r["status"] == "awaiting_approval" and not r["grounding"]["passed"]


# ---------- url fetch safety
def test_url_fetch_disabled_by_default():
    with pytest.raises(PermissionError, match="disabled"):
        fetch_url("https://example.com")


def test_url_fetch_blocks_private_hosts(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_FETCH", True)
    for u in ("http://127.0.0.1/", "http://localhost:8000/", "file:///etc/passwd", "http://169.254.169.254/"):
        with pytest.raises(PermissionError):
            fetch_url(u)


# ---------- API
def test_api_flow(tmp_path, monkeypatch):
    from leadagent import api
    api._store = pipeline.RunStore(tmp_path)
    c = TestClient(api.app)
    assert "brew_bloom_cafe" in c.get("/api/info").json()["fixtures"]
    run = c.post("/api/runs", json={"source": "brew_bloom_cafe"}).json()
    assert run["status"] == "awaiting_approval" and "_site_text" not in run
    assert c.get(f"/api/runs/{run['id']}").json()["business"] == "Brew & Bloom Cafe"
    assert c.post(f"/api/runs/{run['id']}/decision", json={"action": "bogus"}).status_code == 409
    assert c.post(f"/api/runs/{run['id']}/decision", json={"action": "approve"}).json()["status"] == "approved"
    assert c.post(f"/api/runs/{run['id']}/decision", json={"action": "approve"}).status_code == 409
    assert c.get("/api/runs/zzzz").status_code == 404
    assert len(c.get("/api/runs").json()) == 1
    assert "LeadAgent" in c.get("/").text
