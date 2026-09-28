"""
PHASE 8 — EVALS: measuring the agent instead of guessing.

Until now, "is the agent good?" meant asking a few questions and eyeballing
the answers. That doesn't scale, and it lies to you: an agent that passed a
question once can fail it the next time (we saw this with F1 in Phase 5).

An eval is just three things:
  1. a fixed set of test questions        -> evals/cases.json
  2. a way to run the agent on all of them -> run_case()
  3. automatic checks that score each run  -> grade()

Then any change (a new prompt, a different model) gives you a NUMBER to
compare, not a feeling. Run it before and after, and you know.

One rule matters more than any check: an INFRASTRUCTURE failure (rate
limit, daily quota, no internet) is not a wrong answer. Those cases are
reported as "skipped" and left out of the pass rate. Otherwise the score
measures your API quota instead of your agent.

Usage (from the project root):
  python -m evals.run                          # default model, every case
  python -m evals.run --model openai/gpt-oss-120b
  python -m evals.run --all                    # compare every available model
  python -m evals.run --repeat 3               # run each case 3 times (flakiness)
  python -m evals.run --only search            # only cases with this tag or id
  python -m evals.run --regrade evals/results/<file>.json   # re-score, no model calls
  python -m evals.run --model gpt-5.4-mini --include-paid   # paid models need this flag

Paid models (OpenAI) are never run unless you pass --include-paid: a full
run is dozens of billed requests per model, so it has to be a choice.
"""

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import openai

from ai.agent import run_agent
from ai.llm import DEFAULT_MODEL, available_models, get_model

EVALS_DIR = Path(__file__).parent
CASES_FILE = EVALS_DIR / "cases.json"
RESULTS_DIR = EVALS_DIR / "results"  # git-ignored

COLOR = sys.stdout.isatty()
def green(s): return f"\033[32m{s}\033[0m" if COLOR else s
def red(s):   return f"\033[31m{s}\033[0m" if COLOR else s
def dim(s):   return f"\033[2m{s}\033[0m" if COLOR else s
def yellow(s): return f"\033[33m{s}\033[0m" if COLOR else s
def bold(s):  return f"\033[1m{s}\033[0m" if COLOR else s


# ---------------------------------------------------------------------------
# 1. Run one case through the real agent
# ---------------------------------------------------------------------------

def run_case(case: dict, model_id: str) -> dict:
    """Ask the agent one question and record everything that happened."""
    events, error, infra = [], None, None
    started = time.perf_counter()
    try:
        for event in run_agent(case["question"], case.get("history", []), model_id):
            if event["type"] != "token":  # tokens are just the answer, piece by piece
                events.append(event)
    except Exception as e:  # a crash is a failed case, not a crashed eval
        error = f"{type(e).__name__}: {e}"
        infra = infra_problem(e)

    answer = next((e for e in events if e["type"] == "answer"), {})
    return {
        "answer": answer.get("text", ""),
        "sources": answer.get("sources", []),
        "tools": [e["tool"] for e in events if e["type"] == "tool_call"],
        "retries": sum(e["type"] == "retry" for e in events),
        "seconds": round(time.perf_counter() - started, 1),
        "error": error,
        "infra": infra,  # None, or why the provider couldn't run this case
    }


def infra_problem(e: Exception) -> dict | None:
    """Was this the provider's fault (quota, network, key) rather than the
    agent's? Returns {"reason", "fatal", "wait"} or None if it's a real failure."""
    if isinstance(e, openai.RateLimitError):
        message = e.body.get("message", str(e)) if isinstance(e.body, dict) else str(e)
        wait = re.search(r"try again in ([\w.]+)", message)
        per_day = "per day" in message.lower() or "(TPD)" in message or "(RPD)" in message
        no_credit = getattr(e, "code", None) == "insufficient_quota" or "insufficient_quota" in str(e)  # OpenAI: out of money
        return {
            "reason": "no credit left" if no_credit else "daily quota used up" if per_day else "rate limit",
            "fatal": per_day or no_credit,  # these won't clear by retrying the next case
            "wait": wait.group(1).rstrip(".") if wait else None,
        }
    if isinstance(e, (openai.APIConnectionError, ConnectionError)):
        return {"reason": "can't reach the model provider", "fatal": True, "wait": None}
    if isinstance(e, openai.AuthenticationError):
        return {"reason": "API key rejected", "fatal": True, "wait": None}
    return None


# ---------------------------------------------------------------------------
# 2. Grade it: every check is plain code, so the score is repeatable
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Make text easy to search: lower case, no **bold**, and fancy unicode
    spaces/hyphens (models love "Python 3.14") turned into plain ones."""
    text = unicodedata.normalize("NFKC", text).replace("‐", "-").replace("‑", "-")
    return re.sub(r"\s+", " ", text.replace("**", "")).lower()


def grade(case: dict, run: dict) -> list[dict]:
    """Returns one {"check": ..., "passed": ...} per expectation in the case."""
    if run["error"]:
        return [{"check": "ran without error", "passed": False, "detail": run["error"]}]

    expect = case["expect"]
    text = normalize(run["answer"])
    checks = []

    # "contains": every item must appear. An item that is a list means
    # "any one of these" (e.g. the height in metres OR in feet).
    for item in expect.get("contains", []):
        options = item if isinstance(item, list) else [item]
        checks.append({
            "check": "mentions " + " / ".join(options),
            "passed": any(normalize(o) in text for o in options),
        })

    for item in expect.get("not_contains", []):
        checks.append({"check": f"doesn't say {item!r}", "passed": normalize(item) not in text})

    # Behaviour checks: did it use the right tools, and not too many?
    for tool in expect.get("tools_used", []):
        checks.append({"check": f"used {tool}", "passed": tool in run["tools"]})

    if "max_tool_calls" in expect:
        limit = expect["max_tool_calls"]
        checks.append({
            "check": "no tools" if limit == 0 else f"at most {limit} tool calls",
            "passed": len(run["tools"]) <= limit,
            "detail": f"used {len(run['tools'])}: {run['tools']}" if len(run["tools"]) > limit else "",
        })

    # Citations: there must be at least one, and every number must point to a
    # source the agent really saw. A made-up [7] is a hallucinated citation.
    if expect.get("cites"):
        cited = cited_ids(run["answer"])
        real = {s["id"] for s in run["sources"]}
        checks.append({"check": "cites a source", "passed": bool(cited)})
        checks.append({
            "check": "citations are real",
            "passed": cited <= real,
            "detail": f"made up: {sorted(cited - real)}" if cited - real else "",
        })

    return checks


# Models write citations in different styles. We accept exactly what the UI
# turns into a citation pill (linkCitations in frontend/src/utils.js):
#     [1]   [1, 3]              most models
#     【1】  【1†L31-L38】        GPT-OSS, from how OpenAI trained it
# Lesson learned the hard way: the grader must judge what the USER sees. The
# first version only looked for [1] and failed GPT-OSS for citations it had.
CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\](?!\()|【(\d+)[^】]*】")


def cited_ids(text: str) -> set[int]:
    """Every source number the answer cites."""
    ids = set()
    for plain, lenticular in CITATION.findall(text):
        for n in (plain or lenticular).split(","):
            ids.add(int(n))
    return ids


# ---------------------------------------------------------------------------
# 3. Run every case for a model and report
# ---------------------------------------------------------------------------

def evaluate(model_id: str, cases: list[dict], repeat: int) -> dict:
    model_name = get_model(model_id)["name"]
    print(bold(f"\n{model_name}") + dim(f"  ({model_id}, {len(cases)} cases × {repeat})"))

    rows, stopped = [], None
    for case in cases:
        for attempt in range(1, repeat + 1):
            if stopped:  # the provider is out for this model; don't waste requests
                rows.append({"case": case["id"], "attempt": attempt, "status": "skipped", "infra": stopped})
                continue

            run = run_case(case, model_id)
            if run["infra"]:
                # Not the agent's fault, so it's neither a pass nor a fail
                row = {"case": case["id"], "attempt": attempt, "status": "skipped", **run}
                if run["infra"]["fatal"]:
                    stopped = run["infra"]
            else:
                checks = grade(case, run)
                status = "passed" if all(c["passed"] for c in checks) else "failed"
                row = {"case": case["id"], "attempt": attempt, "status": status, "checks": checks, **run}
            rows.append(row)
            print_row(row, repeat)

    if stopped:
        wait = f" Try again in {stopped['wait']}," if stopped.get("wait") else ""
        print(yellow(f"  Stopped early: {stopped['reason']}.{wait} or test another model (the local one has no limits)."))
    return {"summary": summarize(model_id, model_name, rows, repeat), "runs": rows}


def regrade(path: Path, cases: list[dict]) -> list[dict]:
    """Score a saved run again with the CURRENT checks. No model is called.

    Running is slow and costs tokens; grading is instant and free. Keeping the
    raw answers means that when you fix a check (or a case's expected answer),
    you get the corrected score without re-running anything."""
    saved = json.loads(path.read_text())
    by_id = {c["id"]: c for c in cases}
    repeat = saved.get("repeat", 1)
    results = []
    for result in saved["results"]:
        model_id, name = result["summary"]["model"], result["summary"]["name"]
        print(bold(f"\n{name}") + dim(f"  (re-graded from {path.name}, no model calls)"))
        rows = []
        for row in result["runs"]:
            if row["case"] not in by_id:  # case was removed, or filtered out with --only
                continue
            if row["status"] != "skipped":
                row["checks"] = grade(by_id[row["case"]], row)
                row["status"] = "passed" if all(c["passed"] for c in row["checks"]) else "failed"
            rows.append(row)
            print_row(row, repeat)
        results.append({"summary": summarize(model_id, name, rows, repeat), "runs": rows})
    return results


def print_row(row: dict, repeat: int):
    label = row["case"] + (f" #{row['attempt']}" if repeat > 1 else "")
    if row["status"] == "skipped":
        if "seconds" in row:  # skipped rows after an early stop aren't printed one by one
            print(f"  {yellow('–')} {label:28} {yellow('skipped: ' + row['infra']['reason'])}")
        return
    stats = dim(f"{row['seconds']:>5}s  {len(row['tools'])} tools" + (f"  {row['retries']} retries" if row["retries"] else ""))
    print(f"  {green('✔') if row['status'] == 'passed' else red('✘')} {label:28} {stats}")
    for c in row["checks"]:
        if not c["passed"]:
            print(f"      {red('✘')} {c['check']}" + (dim(f" — {c['detail']}") if c.get("detail") else ""))


def summarize(model_id: str, name: str, rows: list[dict], repeat: int) -> dict:
    ran = [r for r in rows if r["status"] != "skipped"]
    n = len(ran)
    summary = {
        "model": model_id,
        "name": name,
        "passed": sum(r["status"] == "passed" for r in ran),
        "failed": sum(r["status"] == "failed" for r in ran),
        "skipped": len(rows) - n,
        "total": len(rows),
        # The pass rate only counts cases that actually ran
        "pass_rate": sum(r["status"] == "passed" for r in ran) / n if n else None,
        "avg_seconds": sum(r["seconds"] for r in ran) / n if n else 0,
        "avg_tools": sum(len(r["tools"]) for r in ran) / n if n else 0,
        "retries": sum(r["retries"] for r in ran),
    }
    # A case is "flaky" if it passed on some attempts and failed on others
    if repeat > 1:
        by_case = {}
        for r in ran:
            by_case.setdefault(r["case"], []).append(r["status"] == "passed")
        summary["flaky"] = [c for c, results in by_case.items() if 0 < sum(results) < len(results)]

    if n == 0:
        print(yellow("  Nothing ran, so there's no score for this model."))
    else:
        rate = f"{summary['passed']}/{n} passed ({summary['pass_rate']:.0%})"
        skipped = yellow(f"   {summary['skipped']} skipped") if summary["skipped"] else ""
        print(f"  {bold(rate)}{skipped}" + dim(f"   avg {summary['avg_seconds']:.1f}s · {summary['avg_tools']:.1f} tools/question"))
    if summary.get("flaky"):
        print(dim(f"  flaky: {', '.join(summary['flaky'])}"))
    return summary


def print_comparison(results: list[dict]):
    print(bold("\nComparison"))
    print(f"  {'Model':16} {'Passed':>8} {'Rate':>6} {'Avg time':>9} {'Tools/q':>8} {'Retries':>8} {'Skipped':>8}")
    for r in sorted(results, key=lambda r: (-(r["summary"]["pass_rate"] or 0), r["summary"]["avg_seconds"])):
        s = r["summary"]
        ran = s["total"] - s["skipped"]
        rate = f"{s['pass_rate']:.0%}" if s["pass_rate"] is not None else "–"
        print(f"  {s['name']:16} {s['passed']:>4}/{ran:<3} {rate:>6} "
              f"{s['avg_seconds']:>8.1f}s {s['avg_tools']:>8.1f} {s['retries']:>8} {s['skipped']:>8}")
    print(dim("  (the pass rate only counts questions that actually ran)"))


def main():
    parser = argparse.ArgumentParser(description="Score the agent on a fixed set of test questions.")
    parser.add_argument("--model", action="append", help="model id to test (repeat the flag for several)")
    parser.add_argument("--all", action="store_true", help="test every model that's available right now")
    parser.add_argument("--repeat", type=int, default=1, help="run each case N times to spot flaky ones")
    parser.add_argument("--only", help="only run cases with this tag or id")
    parser.add_argument("--regrade", metavar="FILE", help="re-score a saved results file with the current checks (no model calls)")
    parser.add_argument("--include-paid", action="store_true", help="allow paid models (OpenAI). Each run costs money")
    args = parser.parse_args()

    cases = json.loads(CASES_FILE.read_text())
    if args.only:
        cases = [c for c in cases if args.only == c["id"] or args.only in c.get("tags", [])]
        if not cases:
            sys.exit(f"No case has the id or tag {args.only!r}.")

    if args.regrade:
        results = regrade(Path(args.regrade), cases)
        if len(results) > 1:
            print_comparison(results)
        sys.exit(0 if all_passed(results) else 1)

    model_ids = pick_models(args)

    results = [evaluate(m, cases, args.repeat) for m in model_ids]
    if len(results) > 1:
        print_comparison(results)

    # Save everything (including the raw answers), so you can compare today's
    # run with next week's, or re-grade it later with --regrade
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out = RESULTS_DIR / f"{stamp}.json"
    out.write_text(json.dumps({"when": stamp, "repeat": args.repeat, "results": results}, indent=2))
    print(dim(f"\nSaved: {out.relative_to(EVALS_DIR.parent)}   (re-score it later: --regrade {out.relative_to(EVALS_DIR.parent)})"))

    sys.exit(0 if all_passed(results) else 1)


def pick_models(args) -> list[str]:
    """Which models to test. Paid models only with --include-paid."""
    if args.all:
        usable = [m for m in available_models() if m["available"]]
        skipped = [m["id"] for m in usable if m["paid"] and not args.include_paid]
        if skipped:
            print(dim(f"Skipping paid models (add --include-paid to test them): {', '.join(skipped)}"))
        return [m["id"] for m in usable if m["id"] not in skipped]

    model_ids = args.model or [DEFAULT_MODEL]
    for m in model_ids:
        model = get_model(m)
        if model is None:
            known = ", ".join(x["id"] for x in available_models())
            sys.exit(f"Unknown model {m!r}. Known models: {known}")
        if model.get("paid") and not args.include_paid:
            sys.exit(f"{m} is a paid model: an eval run is dozens of billed requests. "
                     f"Add --include-paid if you really want to run it.")
    return model_ids


def all_passed(results: list[dict]) -> bool:
    """True only if every case ran AND passed, so this can gate a CI pipeline
    later. Skipped cases aren't a pass: we simply don't know the answer."""
    return all(r["summary"]["passed"] == r["summary"]["total"] for r in results)


if __name__ == "__main__":
    main()
