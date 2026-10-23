"""AI Search Optimization agent: Discovery -> Analysis -> Action -> Measurement.

    python3 agent.py --demo                 # full loop offline with fake data (no keys)
    python3 agent.py --quick                # live, small: 8 queries x 1 run (~5 min)
    python3 agent.py                        # live, full run on Café Athena
    python3 agent.py --act                  # ...and ask the owner to approve actions at the end
    python3 agent.py measure --label week2  # later: re-measure live and compare to baseline

    # Free, no API key: analyze answers collected from the free AI apps
    python3 agent.py --manual answers/*.csv
    python3 agent.py measure --manual answers/week2/*.csv   # later, after publishing fixes

    # Any other restaurant:
    python3 agent.py --name "Joe's Diner" --website https://joesdiner.com \\
        --location "Mission Hills, San Diego, CA" --cuisine American
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
DATA, OUT = ROOT / "data", ROOT / "artifacts"
KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "PERPLEXITY_API_KEY"]
STAGES = {
    "discover": "DISCOVERY  - asking AI assistants what diners ask",
    "manual": "DISCOVERY  - importing answers collected from AI apps",
    "analyze": "ANALYSIS   - scoring visibility, competitors and sources",
    "audit": "ANALYSIS   - auditing the website, cited pages and fact consistency",
    "compare": "ANALYSIS   - head to head with each leading rival",
    "diagnose": "ANALYSIS   - explaining why competitors win",
    "generate": "ACTION     - writing schema, FAQ, pages and outreach",
    "act": "ACTION     - owner approves changes",
    "experiment": "MEASUREMENT - before/after test",
    "report": "MEASUREMENT - building the report",
    "dashboard": "MEASUREMENT - building the interactive dashboard",
}


def run(script, *args, env=None, label=None):
    title = STAGES.get(script.replace(".py", ""), script)
    print(f"\n=== {title} ===", flush=True)
    t = time.time()
    r = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT, env=env)
    if r.returncode != 0:
        raise SystemExit(f"\n{script} failed (exit {r.returncode}). Fix the error above, then re-run; "
                         "finished API calls are saved and won't be repeated.")
    print(f"    ({time.time() - t:.0f}s)")


def discover(a, label, limit, env):
    if a.manual:
        run("manual.py", *a.manual, "--label", label, env=env)
    else:
        run("discover.py", "--label", label, *limit, env=env)


def set_target(a):
    """Write data/target.json for a non-default restaurant (only facts given)."""
    if not a.name:
        return
    parts = [p.strip() for p in (a.location or "").split(",") if p.strip()]
    neighborhood = parts[0] if len(parts) >= 2 else None
    city = parts[1] if len(parts) >= 2 else (parts[0] if parts else None)
    region = parts[2] if len(parts) >= 3 else None
    domain = (a.website or "").split("//")[-1].split("/")[0].removeprefix("www.") or None
    target = {"name": a.name, "aliases": [a.name.lower()], "website": a.website, "domain": domain,
              "street": a.street, "city": city, "region": region, "postal": None,
              "neighborhood": neighborhood, "cuisine": [c.strip() for c in (a.cuisine or "").split(",") if c.strip()],
              "founded": None, "hours": [], "highlights": [h.strip() for h in (a.highlight or [])]}
    old = json.loads((DATA / "target.json").read_text()) if (DATA / "target.json").exists() else {}
    if old.get("name") != a.name:
        reset()
    DATA.mkdir(exist_ok=True)
    (DATA / "target.json").write_text(json.dumps(target, indent=2, ensure_ascii=False))
    print(f"Target set to {a.name}. Add --highlight \"...\" facts to improve generated content.")


def reset():
    for p in [DATA / "runs", OUT]:
        shutil.rmtree(p, ignore_errors=True)
    for p in DATA.glob("*"):
        if p.is_file():
            p.unlink()
    OUT.mkdir(exist_ok=True)


def summary(label, after=None):
    sys.path.insert(0, str(ROOT))
    from config import read_json
    from report import five_answers
    card = read_json(DATA / f"scorecard_{label}.json")
    after_card = read_json(DATA / f"scorecard_{after}.json") if after else None
    answers = five_answers(label, card, after_card)
    (DATA / "summary.json").write_text(json.dumps(
        {"label": label, "after": after, "answers": answers}, ensure_ascii=False, indent=2))
    print("\n" + "=" * 70)
    for q, ans in answers:
        print(f"\n{q}\n  {ans}")
    print("\n" + "=" * 70)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "measure", "reset"])
    ap.add_argument("--demo", action="store_true", help="offline fake data, no API keys")
    ap.add_argument("--quick", action="store_true", help="8 queries x 1 run")
    ap.add_argument("--act", action="store_true", help="ask for owner approval at the end")
    ap.add_argument("--label", default=None)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--manual", nargs="+", metavar="CSV", help="free mode: answers collected by hand")
    ap.add_argument("--name"), ap.add_argument("--website"), ap.add_argument("--location")
    ap.add_argument("--street"), ap.add_argument("--cuisine")
    ap.add_argument("--highlight", action="append", help="a verified fact; repeat for several")
    a = ap.parse_args()

    if a.command == "reset":
        reset()
        return print("Cleared data/ and artifacts/ (target back to Café Athena).")

    env = dict(os.environ)
    has_key = any(env.get(k) for k in KEYS)
    if a.demo:
        env["MOCK"] = "1"
    elif not has_key and not a.manual:
        raise SystemExit("No API key found. Options:\n    python3 agent.py --demo                    (fake data)\n"
                         "    python3 agent.py --manual answers/*.csv    (free: answers from AI apps)\n"
                         "or set a key first, e.g.:\n    export ANTHROPIC_API_KEY=sk-ant-...")
    if a.quick:
        env["RUNS"] = "1"
    set_target(a)

    label = a.label or ("demo" if a.demo else "baseline")
    limit = ["--limit", "8"] if a.quick else []

    if a.command == "measure":
        base = "demo" if a.demo else "baseline"
        if label == base:
            label = "rerun-" + time.strftime("%Y%m%d-%H%M")
        discover(a, label, limit, env)
        run("analyze.py", "--label", label, env=env)
        run("report.py", "--label", base, "--after", label, env=env)
        run("dashboard.py", "--label", base, env=env)
        summary(base, label)
    else:
        if not (DATA / "queries.json").exists() or a.name:
            subprocess.run([sys.executable, str(ROOT / "queries.py")], cwd=ROOT, env=env, check=True)
        if a.demo:  # demo always starts clean so numbers are reproducible
            (DATA / "runs" / "demo.jsonl").unlink(missing_ok=True)
        discover(a, label, limit, env)
        run("analyze.py", "--label", label, env=env)
        run("audit.py", "--label", label, env=env)
        run("compare.py", "--label", label, env=env)
        run("diagnose.py", "--label", label, env=env)
        run("generate.py", "--label", label, env=env)
        if a.act:
            run("act.py", env=env)
        if a.demo or has_key:
            run("experiment.py", "--label", label, *(["--n", "8", "--runs", "1"] if a.quick else []), env=env)
        else:
            (DATA / "experiment.json").unlink(missing_ok=True)
            print("\n(Skipping the simulated before/after test: it needs an API key. "
                  "Measure for free by re-asking the same questions after publishing fixes.)")
        run("report.py", "--label", label, env=env)
        run("dashboard.py", "--label", label, env=env)
        summary(label)

    report = OUT / "report.html"
    print(f"\nReport: {report}")
    if not a.no_open and report.exists():
        webbrowser.open(report.resolve().as_uri())


if __name__ == "__main__":
    main()
