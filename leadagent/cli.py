"""CLI: python -m leadagent run <fixture|url> | list | show <id> | decide <id> approve|reject|edit"""
import argparse
import json
import sys

from .pipeline import RunStore, decide, public, start_run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="leadagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("source"); r.add_argument("--force", action="store_true")
    sub.add_parser("list")
    s = sub.add_parser("show"); s.add_argument("id")
    d = sub.add_parser("decide"); d.add_argument("id"); d.add_argument("action", choices=["approve", "reject", "edit"])
    d.add_argument("--reason", default=""); d.add_argument("--body")
    a = ap.parse_args(argv)
    st = RunStore()
    if a.cmd == "run":
        run = start_run(a.source, st, a.force)
        print(f"run {run['id']}  status={run['status']}  business={run['business']}  score={run['score']}")
        for t in run["trace"]:
            print(f"  [{t['mode']:5s}] {t['step']:20s} {t['summary']}")
        if run["draft"]:
            print("\n--- DRAFT (awaiting your decision) ---\n" + run["draft"]["subject"] + "\n\n" + run["draft"]["body"])
    elif a.cmd == "list":
        for r in st.list(): print(r["id"], r["status"], r["score"], r["business"])
    elif a.cmd == "show":
        print(json.dumps(public(st.get(a.id)), indent=1))
    else:
        run = decide(st, a.id, a.action, body=a.body, reason=a.reason); print(run["status"])


if __name__ == "__main__":
    main()
