from __future__ import annotations
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, config, llm
from .pipeline import RunStore, decide, public, start_run
from .score import RUBRIC

DASH = config.ROOT / "dashboard"
app = FastAPI(title="LeadAgent", version=__version__)
_store: RunStore | None = None


def store() -> RunStore:
    global _store
    if _store is None:
        _store = RunStore()
    return _store


class Start(BaseModel):
    source: str = Field(min_length=3, max_length=200_000)
    force_draft: bool = False


class Decision(BaseModel):
    action: str
    subject: str | None = None
    body: str | None = None
    reason: str = ""


@app.get("/api/info")
def info():
    return {"version": __version__, "llm": ("llm:" + config.LLM_MODEL) if llm.enabled() else "none (deterministic templates)",
            "url_fetch": config.ALLOW_FETCH, "min_fit": config.MIN_FIT_TO_DRAFT,
            "fixtures": sorted(p.stem for p in config.FIXTURES.glob("*.html")),
            "rubric": [{"id": r[0], "max": r[1], "description": r[2]} for r in RUBRIC]}


@app.get("/api/runs")
def runs():
    return store().list()


@app.post("/api/runs")
def new_run(b: Start):
    return public(start_run(b.source, store(), b.force_draft))


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    try:
        return public(store().get(rid))
    except KeyError:
        raise HTTPException(404, "no such run")


@app.post("/api/runs/{rid}/decision")
def post_decision(rid: str, d: Decision):
    try:
        return public(decide(store(), rid, d.action, d.subject, d.body, d.reason))
    except KeyError:
        raise HTTPException(404, "no such run")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/")
def index():
    return FileResponse(DASH / "index.html")


app.mount("/static", StaticFiles(directory=DASH), name="static")
