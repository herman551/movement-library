#!/usr/bin/env python3
"""Author movement records, one name at a time, into data/movements.json.

    python3 tools/generate.py                 # everything in names.txt not already authored
    python3 tools/generate.py --limit 5       # a taste, to read before spending
    python3 tools/generate.py --only "Front Squat" --only "Seal Row"
    python3 tools/generate.py --dry-run       # what it WOULD do, no calls, no cost

Two passes per movement, the shape that stops the thin records: a research pass that reads
the open web and states its findings, then an extraction pass that turns them into the
schema. The questions name the two fields that otherwise come back empty — secondary
muscles, and like-lift ratios.

THE KEY IS NEVER IN THIS FILE, in a flag, or on screen. It is read at runtime from the
macOS Keychain (the same item Coach stores), or from ANTHROPIC_API_KEY if you prefer to
export it yourself. Nothing here prints it, logs it, or writes it anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAMES = ROOT / "tools" / "names.txt"
DATA = ROOT / "data" / "movements.json"
SCHEMA = ROOT / "schema" / "movement.schema.json"

API = "https://api.anthropic.com/v1/messages"
VERSION = "2023-06-01"
RESEARCH_MODEL = "claude-sonnet-5"
EXTRACT_MODEL = "claude-sonnet-5"

KEYCHAIN_SERVICE = "com.justinherman.FitnessHub"
KEYCHAIN_ACCOUNT = "anthropic-api-key"

RESEARCH_SYSTEM = """\
You are a strength & conditioning researcher building a reference record for one movement.
State each of these explicitly in your summary:

1. Its most standard gym name, and other common names for the SAME movement.
2. Its movement pattern — squat, hinge, lunge, horizontal push, vertical push, horizontal
   pull, vertical pull, carry/core, or none for isolation work — and how it is loaded
   (barbell, dumbbell, kettlebell, machine, cable, landmine, bodyweight, band, sled).
3. Whether it is multi-joint (compound) or single-joint (isolation), and whether the working
   effort is a push, a pull, or static.
4. The PRIMARY muscle, named on its own.
5. The SECONDARY muscles — every muscle doing meaningful work, listed by name. Name them even
   for an isolation exercise; almost none has none. A recovery model credits these, so an
   empty list under-counts somebody's training.
6. One to three LIKE LIFTS whose strength transfers, each with a load ratio: "this movement
   is about R times that movement" at the same reps, R from published training standards or
   well-established coaching practice. Compare against COMMON, heavily documented lifts,
   closest relative first. Say plainly when nothing is well established rather than guessing.
7. Whether it is trained one side at a time, and whether an estimated one-rep max is
   meaningful for it.
8. What a room needs beyond the load type (a rack with safeties, a bench at 30-45°, rings).

Describe THE MOVEMENT NAMED, not a more common relative of it. A box squat, a pause squat
and a safety bar squat are each their own movement: say what is true of that one, and give
its ratio against the common lift it is a variant of.

Use web search to confirm. Describe facts about the movement. Do NOT write coaching
instructions, cues, or step-by-step technique: this record carries facts, not prose.
"""

EXTRACT_SYSTEM = """\
Turn this research summary into one JSON object matching the schema. Output only the JSON.

secondaryMuscles: carry every muscle the summary names as doing meaningful work, MOST
significant first, up to six. Never empty for a loaded movement — if the summary is vague,
name the muscles its description implies. Each entry is ONE muscle from the allowed list — never a phrase
like "Trapezius and Rhomboids" or "deep spinal stabilizers". Map the summary's wording onto
the closest allowed value and drop anything that has none. Leave the list empty only when the
summary genuinely names no secondary work.

transfers: every like-lift ratio the summary states, as "this movement is about RATIO times
REFERENCE at the same reps". The reference must be one of the allowed lifts; if the summary
compares against something not on that list, either express it against an allowed lift or
leave it out. When the movement is a VARIANT of an allowed lift (a low-bar squat of a back
squat, an incline dumbbell press of a dumbbell bench press), give the ratio against that lift
— that comparison is the one a reader most needs. Do not invent a ratio the summary did not
state; if it states none, return an empty list.

aliases: other names for THE SAME movement. Not a narrower variant that people train as its
own exercise (a high-bar and a low-bar squat are variants, not aliases), and nothing generic
like "the squat".

Write no instructional prose: there is no field for it and none is wanted.
"""

# A muscle is a VALUE, not a phrase. The first run produced "Quadratus Lumborum and deep
# spinal stabilizers" and "Trapezius (upper/middle) and Rhomboids" — unusable by anything that
# wants to add up a week's work per muscle. Closed vocabulary, atomic entries.
MUSCLES = [
    "Upper Trapezius", "Middle Trapezius", "Lower Trapezius", "Rhomboids",
    "Latissimus Dorsi", "Teres Major", "Erector Spinae", "Quadratus Lumborum",
    "Anterior Deltoid", "Lateral Deltoid", "Posterior Deltoid", "Rotator Cuff",
    "Serratus Anterior", "Pectoralis Major", "Pectoralis Minor",
    "Biceps Brachii", "Brachialis", "Brachioradialis", "Triceps Brachii",
    "Forearm Flexors", "Forearm Extensors", "Grip",
    "Rectus Abdominis", "Obliques", "Transverse Abdominis", "Hip Flexors",
    "Gluteus Maximus", "Gluteus Medius", "Gluteus Minimus",
    "Adductors", "Quadriceps", "Hamstrings",
    "Gastrocnemius", "Soleus", "Tibialis Anterior", "Peroneals",
    "Neck Flexors", "Neck Extensors",
]

# A transfer is only useful if its reference resolves to something. Free text gave
# "Deadlift (conventional)", which matches nothing. Closed set of common, heavily documented
# lifts — every one of them a seed name in names.txt.
REFERENCE_LIFTS = [
    "Back Squat", "Front Squat", "Leg Press", "Hack Squat Machine", "Bulgarian Split Squat",
    "Conventional Deadlift", "Sumo Deadlift", "Trap Bar Deadlift", "Romanian Deadlift",
    "Barbell Hip Thrust", "Kettlebell Swing",
    "Barbell Bench Press", "Incline Barbell Bench Press", "Dumbbell Bench Press",
    "Machine Chest Press", "Push-Up", "Chest Dip",
    "Overhead Press", "Dumbbell Shoulder Press", "Machine Shoulder Press",
    "Pull-Up", "Chin-Up", "Lat Pulldown",
    "Barbell Row", "Dumbbell Row", "Seated Cable Row", "T-Bar Row",
    "Barbell Curl", "Dumbbell Curl", "Triceps Pushdown", "Skullcrusher",
    "Dumbbell Lateral Raise", "Leg Extension", "Lying Leg Curl", "Standing Calf Raise",
    "Farmer's Walk", "Plank",
]

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "pattern": {"type": "string", "enum": ["squat", "hinge", "lunge", "horizontalPush",
                                               "verticalPush", "horizontalPull", "verticalPull",
                                               "carryCore", "none"]},
        "loadType": {"type": "string", "enum": ["barbell", "dumbbell", "kettlebell", "machine",
                                                "cable", "landmine", "bodyweight", "band",
                                                "sled", "other"]},
        "mechanic": {"type": "string", "enum": ["compound", "isolation"]},
        "force": {"type": "string", "enum": ["push", "pull", "static"]},
        "primaryMuscle": {"type": "string", "enum": MUSCLES},
        "secondaryMuscles": {"type": "array", "items": {"type": "string", "enum": MUSCLES},
                             "minItems": 1, "maxItems": 6},
        "unilateral": {"type": "boolean"},
        "strengthTracked": {"type": "boolean"},
        "transfers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "enum": REFERENCE_LIFTS},
                    "ratio": {"type": "number"},
                    "basis": {"type": "string", "enum": ["published", "practice"]},
                },
                "required": ["reference", "ratio", "basis"],
                "additionalProperties": False,
            },
        },
        "equipmentNotes": {"type": "string"},
    },
    "required": ["name", "aliases", "pattern", "loadType", "mechanic", "force",
                 "primaryMuscle", "secondaryMuscles", "unilateral", "strengthTracked",
                 "transfers"],
    "additionalProperties": False,
}


def api_key() -> str:
    """From the environment if exported, else the Keychain. Never printed, never stored."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except subprocess.CalledProcessError:
        sys.exit("No API key. Export ANTHROPIC_API_KEY, or store one in the Keychain "
                 f"(service {KEYCHAIN_SERVICE}, account {KEYCHAIN_ACCOUNT}).")


def call(key: str, body: dict, retries: int = 2, timeout: int = 180) -> dict:
    data = json.dumps(body).encode()
    request = urllib.request.Request(API, data=data, method="POST", headers={
        "content-type": "application/json",
        "anthropic-version": VERSION,
        "x-api-key": key,
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise RuntimeError(f"HTTP {error.code}: {error.read()[:200].decode(errors='replace')}")
        except (urllib.error.URLError, TimeoutError):
            # One slow name must not cost the run minutes: fail it, let the next run retry it
            # (nothing is written for a failure, so it simply comes round again).
            if attempt < retries - 1:
                time.sleep(2)
                continue
            raise TimeoutError("no reply within the deadline")
    raise SystemExit("unreachable")


def text_of(reply: dict) -> str:
    return "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")


def sources_of(reply: dict) -> list[str]:
    """Whatever the research actually opened — provenance, not content.

    A FAILED search returns a dict ({"type": "web_search_tool_result_error", ...}) where
    results are expected; iterating that yields its keys, and asking a string for .get is
    the AttributeError that killed one name in the first five.
    """
    urls: list[str] = []
    for block in reply.get("content", []):
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        results = block.get("content")
        if not isinstance(results, list):
            continue
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if url and url not in urls:
                urls.append(url)
    return urls


def slug(name: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in name]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def research(key: str, name: str) -> tuple[str, list[str]]:
    reply = call(key, {
        "model": RESEARCH_MODEL,
        "max_tokens": 4000,
        "system": RESEARCH_SYSTEM,
        "messages": [{"role": "user", "content": f"Movement: {name}"}],
        "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
    }, timeout=240)
    findings = text_of(reply).strip()
    if not findings:
        raise ValueError("research returned no prose to extract from")
    return findings, sources_of(reply)


def extract(key: str, findings: str) -> dict:
    reply = call(key, {
        "model": EXTRACT_MODEL,
        "max_tokens": 1500,
        "system": EXTRACT_SYSTEM,
        "messages": [{"role": "user", "content": findings}],
        "tools": [{"name": "record", "description": "The movement record.",
                   "input_schema": EXTRACT_SCHEMA}],
        "tool_choice": {"type": "tool", "name": "record"},
    }, timeout=120)
    for block in reply.get("content", []):
        if block.get("type") == "tool_use":
            return block["input"]
    raise ValueError("no record returned")


def load_existing() -> dict[str, dict]:
    if not DATA.exists():
        return {}
    return {r["id"]: r for r in json.loads(DATA.read_text())}


def save(records: dict[str, dict]) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    ordered = [records[k] for k in sorted(records)]
    DATA.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")


def wanted_names(args) -> list[str]:
    if args.only:
        return list(args.only)
    lines = [l.strip() for l in NAMES.read_text().splitlines()]
    return [l for l in lines if l and not l.startswith("#")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=0, help="stop after this many new records")
    parser.add_argument("--only", action="append", help="author just this name (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="list what would be authored")
    parser.add_argument("--redo", action="store_true", help="re-author names already present")
    args = parser.parse_args()

    records = load_existing()
    names = wanted_names(args)
    todo = [n for n in names if args.redo or slug(n) not in records]
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(names)} seed names · {len(records)} already authored · {len(todo)} to do")
    if args.dry_run:
        for n in todo[:40]:
            print("  would author:", n)
        if len(todo) > 40:
            print(f"  … and {len(todo) - 40} more")
        return
    if not todo:
        return

    key = api_key()
    authored = failed = 0
    for index, name in enumerate(todo, start=1):
        try:
            findings, sources = research(key, name)
            record = extract(key, findings)
        except Exception as error:                      # one bad name must not end the run
            failed += 1
            print(f"  [{index}/{len(todo)}] {name}: FAILED ({type(error).__name__})")
            if failed >= 5 and authored == 0:
                sys.exit("five failures and nothing authored — stopping before this costs more")
            continue
        # The seed name owns the record. A canonical name that denotes a DIFFERENT movement
        # (Box Squat → "Back Squat") would collapse two movements into one and overwrite
        # whatever was there; the model's name survives only as an alias.
        returned = (record.get("name") or "").strip()
        if slug(returned) != slug(name):
            aliases = record.get("aliases") or []
            if returned and slug(returned) not in {slug(a) for a in aliases}:
                aliases.append(returned)
            record["aliases"] = aliases
            record["name"] = name
        record["id"] = slug(name)
        record["sources"] = sources[:8]          # provenance, not a bibliography
        record["authored"] = time.strftime("%Y-%m-%d")
        record["reviewed"] = None
        records[record["id"]] = record
        authored += 1
        save(records)                                   # crash-safe: every record is on disk
        print(f"  [{index}/{len(todo)}] {record['name']} — {record['primaryMuscle']}, "
              f"{len(record.get('secondaryMuscles', []))} secondary, "
              f"{len(record.get('transfers', []))} transfer(s)")

    print(f"done: {authored} authored, {failed} failed, {len(records)} in {DATA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
