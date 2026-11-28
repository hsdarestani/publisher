"""Resolve a tested source tree reachable from the integration branch."""
import json
import os
import re
import subprocess

repo = "hsdarestani/taskservice"
base = "codex/taskservice-v2-core"


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/{path}"]))


def resolve(number):
    if not re.fullmatch(r"[1-9][0-9]*", number):
        raise ValueError("A pull request number is required")
    pr = api(f"pulls/{number}")
    if not pr["merged"] or pr["base"]["ref"] != base or pr["head"]["repo"]["full_name"] != repo:
        raise ValueError("The PR must be merged into the TaskService integration branch")
    revision = pr["head"]["sha"]
    merged = api(f"commits/{base}")
    if merged["commit"]["tree"]["sha"] != api(f"git/commits/{revision}")["tree"]["sha"]:
        raise ValueError("The current integration tree differs from the tested PR tree")
    runs = api(f"actions/workflows/taskservice-v2.yml/runs?head_sha={revision}&event=pull_request&per_page=100")
    eligible = [run for run in runs["workflow_runs"] if run["head_sha"] == revision
                and any(p["number"] == int(number) for p in run["pull_requests"])]
    if not eligible or max(eligible, key=lambda run: (run["id"], run["run_attempt"]))["conclusion"] != "success":
        raise ValueError("The latest validation for this PR revision must pass")
    return revision


if __name__ == "__main__":
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as result:
        print("sha=" + resolve(os.environ["SOURCE_PR"]), file=result)
