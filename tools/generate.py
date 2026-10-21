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

Use web search to confirm. Describe facts about the movement. Do NOT write coaching
instructions, cues, or step-by-step technique: this record carries facts, not prose.
"""

EXTRACT_SYSTEM = """\
Turn this research summary into one JSON object matching the schema. Output only the JSON.

Carry EVERY secondary muscle the summary names into secondaryMuscles, and every like-lift
ratio it states into transfers — those two are the fields that go missing. Leave them empty
only when the summary genuinely names none. Do not invent a ratio the summary did not state.
Write no instructional prose: there is no field for it and none is wanted.
"""

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
        "primaryMuscle": {"type": "string"},
        "secondaryMuscles": {"type": "array", "items": {"type": "string"}},
        "unilateral": {"type": "boolean"},
        "strengthTracked": {"type": "boolean"},
        "transfers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reference": {"type": "string"},
                    "ratio": {"type": "number"},
                    "basis": {"type": "string", "enum": ["published", "practice"]},
                },
                "required": ["reference", "ratio"],
                "additionalProperties": False,
            },
        },
        "equipmentNotes": {"type": "string"},
    },
    "required": ["name", "pattern", "loadType", "mechanic", "primaryMuscle"],
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


def call(key: str, body: dict, retries: int = 3) -> dict:
    data = json.dumps(body).encode()
    request = urllib.request.Request(API, data=data, method="POST", headers={
        "content-type": "application/json",
        "anthropic-version": VERSION,
        "x-api-key": key,
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise SystemExit(f"HTTP {error.code}: {error.read()[:300].decode(errors='replace')}")
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise
    raise SystemExit("unreachable")


def text_of(reply: dict) -> str:
    return "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")


def sources_of(reply: dict) -> list[str]:
    """Whatever the research actually opened — provenance, not content."""
    urls: list[str] = []
    for block in reply.get("content", []):
        if block.get("type") == "web_search_tool_result":
            for item in block.get("content", []) or []:
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
        "max_tokens": 2000,
        "system": RESEARCH_SYSTEM,
        "messages": [{"role": "user", "content": f"Movement: {name}"}],
        "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
    })
    return text_of(reply), sources_of(reply)


def extract(key: str, findings: str) -> dict:
    reply = call(key, {
        "model": EXTRACT_MODEL,
        "max_tokens": 1500,
        "system": EXTRACT_SYSTEM,
        "messages": [{"role": "user", "content": findings}],
        "tools": [{"name": "record", "description": "The movement record.",
                   "input_schema": EXTRACT_SCHEMA}],
        "tool_choice": {"type": "tool", "name": "record"},
    })
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
        except SystemExit:
            raise
        except Exception as error:                      # one bad name must not end the run
            failed += 1
            print(f"  [{index}/{len(todo)}] {name}: FAILED ({type(error).__name__})")
            if failed >= 5 and authored == 0:
                sys.exit("five failures and nothing authored — stopping before this costs more")
            continue
        record["id"] = slug(record.get("name") or name)
        record["sources"] = sources
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
