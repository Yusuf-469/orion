"""Post-hoc: which plans accepted WITHOUT the intent-drift check would that check have rejected?

usage: python research/planner_eval/posthoc_intent_check.py RESULT.json
Applies orion.planner.validator.request_paths to the saved plans. Analysis only; it does not
re-query the model, so it cannot tell what the repair round would have produced instead.
"""

import json
import sys
from pathlib import PureWindowsPath

from orion.planner.validator import request_paths

WRITE_TOOLS = {"files.write_new": ("path",), "files.copy": ("dst",), "files.delete": ("path",)}


def norm(p: str) -> str:
    return PureWindowsPath(p).as_posix().strip("/").lower()


res = json.load(open(sys.argv[1], encoding="utf-8"))
prompts = {p["id"]: p for p in json.load(open("research/planner_eval/prompts_v1.json", encoding="utf-8"))["prompts"]}
accepted = [r for r in res["rows"] if r["got"] == "ok"]
caught = []
for r in accepted:
    named = request_paths(prompts[r["id"]]["text"])
    drift = [args[k] for tool, args in r["plan"] for k in WRITE_TOOLS.get(tool, ())
             if isinstance(args.get(k), str) and not args[k].startswith("${")
             and norm(args[k]) not in named and not (norm(args[k]).endswith(".bak") and norm(args[k])[:-4] in named)]
    if drift:
        caught.append((r["id"], r["expect"], drift))
print(f"source: {sys.argv[1]} (commit {res['git_commit']})")
print(f"accepted plans: {len(accepted)}; would be rejected for intent drift: {len(caught)}")
for c in caught:
    print("  ", c)
