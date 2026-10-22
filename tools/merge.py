#!/usr/bin/env python3
"""Validate a batch of hand-authored records and merge them into data/movements.json.

The generator wrote records one at a time with nothing checking the result, which is how
'Overhead Press -> Quadriceps' and a loadType of 'other' on a machine press reached the
file. Everything authored from here on goes through this gate instead: a batch either
passes whole or is refused whole, so a bad record never lands silently.

    python3 tools/merge.py batch.json            # validate and merge
    python3 tools/merge.py batch.json --check    # validate only, write nothing
"""
import json, pathlib, re, sys, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "movements.json"
GEN = (ROOT / "tools" / "generate.py").read_text()

MUSCLES = set(eval(re.search(r'MUSCLES\s*=\s*(\[.*?\])', GEN, re.S).group(1)))
REFS = set(eval(re.search(r'REFERENCE_LIFTS\s*=\s*(\[.*?\])', GEN, re.S).group(1)))
PATTERNS = {"squat","hinge","lunge","horizontalPush","verticalPush",
            "horizontalPull","verticalPull","carryCore","none"}
LOADS = {"barbell","dumbbell","kettlebell","machine","cable","landmine",
         "bodyweight","band","sled","other"}

# A name that says what it is loaded with must agree with loadType. This is the exact
# inconsistency the per-name run produced, so it is worth asserting rather than trusting.
NAME_LOAD = [("Landmine","landmine"), ("Smith Machine","machine"), ("Cable","cable"),
             ("Barbell","barbell"), ("Dumbbell","dumbbell"), ("Kettlebell","kettlebell"),
             ("Machine","machine"), ("Band","band"), ("Sled","sled")]

def slug(name):
    s = name.lower().replace("'", "").replace("’", "")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")

def check(rec, seen, errs):
    where = rec.get("name") or rec.get("id") or "<unnamed>"
    def bad(msg): errs.append(f"{where}: {msg}")

    for f in ("id","name","pattern","loadType","mechanic","primaryMuscle"):
        if not rec.get(f): bad(f"missing required field '{f}'"); return
    if rec["id"] != slug(rec["name"]): bad(f"id {rec['id']!r} != slug of name ({slug(rec['name'])!r})")
    if rec["id"] in seen: bad("duplicate id")
    seen.add(rec["id"])

    if rec["pattern"] not in PATTERNS: bad(f"pattern {rec['pattern']!r} not in enum")
    if rec["loadType"] not in LOADS: bad(f"loadType {rec['loadType']!r} not in enum")
    if rec["mechanic"] not in ("compound","isolation"): bad(f"mechanic {rec['mechanic']!r} not in enum")
    if rec.get("force") not in ("push","pull","static",None): bad(f"force {rec.get('force')!r} not in enum")

    if rec["primaryMuscle"] not in MUSCLES: bad(f"primaryMuscle {rec['primaryMuscle']!r} off-vocabulary")
    sec = rec.get("secondaryMuscles") or []
    for m in sec:
        if m not in MUSCLES: bad(f"secondary {m!r} off-vocabulary")
    if rec["primaryMuscle"] in sec: bad("primaryMuscle repeated in secondaryMuscles")
    if len(sec) != len(set(sec)): bad("duplicate secondaryMuscles")
    # A compound lift that names one muscle and nothing else is the signature of a
    # collapsed extraction, not of a real record.
    if rec["mechanic"] == "compound" and len(sec) < 2:
        bad(f"compound with {len(sec)} secondary muscle(s) — looks collapsed")

    for word, lt in NAME_LOAD:
        if word in rec["name"] and rec["loadType"] != lt:
            bad(f"name says {word!r} but loadType is {rec['loadType']!r}"); break

    for t in rec.get("transfers") or []:
        if t.get("reference") not in REFS: bad(f"transfer reference {t.get('reference')!r} not a reference lift")
        if t.get("reference") == rec["name"]: bad("transfers to itself")
        r = t.get("ratio")
        if not isinstance(r,(int,float)) or not (0 < r <= 3): bad(f"ratio {r!r} out of range")
        if t.get("basis") not in ("published","practice"): bad(f"basis {t.get('basis')!r} not in enum")

    for u in rec.get("sources") or []:
        if not str(u).startswith("http"): bad(f"source {u!r} is not a URL")

    for k in rec:
        if k not in {"id","name","aliases","pattern","loadType","mechanic","force","primaryMuscle",
                     "secondaryMuscles","unilateral","strengthTracked","transfers","equipmentNotes",
                     "sources","authored","reviewed"}:
            bad(f"unknown field {k!r}")

def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    batch = json.loads(pathlib.Path(sys.argv[1]).read_text())
    if isinstance(batch, dict): batch = [batch]
    existing = json.loads(DATA.read_text()) if DATA.exists() else []

    errs, seen = [], set()
    for rec in batch: check(rec, seen, errs)
    if errs:
        print(f"REFUSED — {len(errs)} problem(s), nothing written:")
        for e in errs: print("  •", e)
        sys.exit(1)

    if "--check" in sys.argv:
        print(f"OK — {len(batch)} record(s) valid (not written)"); return

    today = datetime.date.today().isoformat()
    by_id = {r["id"]: r for r in existing}
    added = replaced = 0
    for rec in batch:
        rec.setdefault("authored", today)
        rec.setdefault("reviewed", None)
        if rec["id"] in by_id: replaced += 1
        else: added += 1
        by_id[rec["id"]] = rec

    out = sorted(by_id.values(), key=lambda r: r["id"])
    DATA.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"merged: +{added} new, {replaced} replaced → {len(out)} records")

main()
