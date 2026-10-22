# Movement Library

An openly licensed dataset of resistance-training movements, described in the fields a
program actually computes with: movement pattern, how it loads, compound or isolation,
the muscles it works, and **what a lift transfers from**.

**CC0.** Public domain. No attribution required, no share-alike, nothing to read before you
use it.

```json
{
  "id": "cable-lateral-raise",
  "name": "Cable Lateral Raise",
  "aliases": ["Cable Side Raise", "Single-Arm Cable Lateral Raise"],
  "pattern": "none",
  "loadType": "cable",
  "mechanic": "isolation",
  "force": "push",
  "primaryMuscle": "Lateral Deltoid",
  "secondaryMuscles": ["Anterior Deltoid", "Rotator Cuff", "Upper Trapezius"],
  "unilateral": true,
  "strengthTracked": false,
  "transfers": [{ "reference": "Dumbbell Lateral Raise", "ratio": 1.1, "basis": "practice" }],
  "equipmentNotes": "A low cable pulley with a single handle.",
  "sources": ["https://fitbod.me/exercises/cable-lateral-raise", "..."],
  "authored": "2026-10-22",
  "reviewed": null
}
```

## Why this exists

Every open exercise dataset we could find has one of two problems.

**Provenance.** The most-recommended "public domain" dataset is a fork of a repo whose own
contributing guide says its images "have been scrapped off the internet", with the author
advising against commercial use. Contributors have since traced them to ExRx.net and
bodybuilding.com. A public-domain dedication cannot cover content the dedicator never owned,
so that licence is void as to the parts that matter, and several popular libraries are
downstream of it. Other sets forbid redistribution outright, or state no data licence at all
while shipping media traced to a commercial seller.

**Missing fields.** The one dataset with a genuinely clean, per-record licence chain
([wger](https://github.com/wger-project/wger), CC-licensed, worth your attention) has no
compound-versus-isolation flag, no force vector, and no transfer ratios — and its taxonomy is
eight categories wide, which is how a kettlebell swing ends up filed under "Abs".

This dataset is **originally authored**, not assembled from other people's records. Nothing
is copied from a copyrighted source. That is the whole claim: you can use it without doing
legal archaeology first.

## What's in it, and what isn't

**In:** canonical name, aliases, pattern, load type, mechanic, force vector, primary and
secondary muscles, unilateral flag, whether a one-rep estimate means anything, like-lift
transfer ratios, equipment notes, and the sources the research consulted.

**Not in:**

- **Images or video.** Deliberately. Images are what poisoned every dataset above. Text-only
  is defensible on day one; anything visual here later will be drawn for this repo.
- **Instructional prose.** How to perform a lift is where copying happens and where liability
  lives. Other projects can write their own cues against these facts.
- **Programming advice.** Sets, reps, loads and progressions belong to a coach, not a catalogue.

## How records are made

383 records, one per movement that people actually train, covering 32 of the 38 muscles in
the vocabulary. Every record cites the pages consulted when it was written. Nothing is
copied from any of them: they are read, and the record is written from what they say plus
general training knowledge.

Two things are deliberately closed. Muscles come from a fixed list of 38 anatomical names,
and `transfers.reference` may only name one of 37 common lifts. Open vocabularies are how a
dataset ends up with "upper chest area" in one record and "Pectoralis Major (clavicular)" in
the next, and with ratios pointing at movements that have no record.

Records are written a family at a time — every pulldown grip together, every row together —
and that is not a detail. A record written in isolation has nothing to be consistent *with*:
it is how you get a cable chest press filed under `machine` while the machine chest press is
filed under `other`, and how half a catalogue ends up with no transfer ratio at all. Writing
the family at once puts its variants on one scale.

`tools/merge.py` is the gate every record passes before it lands. It refuses off-vocabulary
muscles, a primary muscle repeated in the secondary list, a load type that contradicts the
name, a compound lift claiming fewer than two secondary muscles, a ratio outside (0, 3], and
a transfer pointing at anything that is not a reference lift. Run it over the whole file and
it checks all 383.

`tools/aliases.txt` records the 16 names deliberately folded into another record rather than
given one of their own. A seed list written quickly has real duplicates in it, and forking a
second record for `Dumbbell Rear Delt Fly` is how a catalogue claims a count it has not earned.

**An empty `transfers` is an answer, not an omission.** Roughly half the set has no ratio,
and most of that half is bodyweight work, isolation, carries, jumps and mobility drills,
where there is no load number to be a ratio *of*. The reference lifts have none because they
are the thing others are measured against. Assisted movements have none on purpose: the
number on an assisted dip machine is assistance, so it moves opposite to strength and a ratio
against a dip would be worse than silence.

Machine-authored records carry `"reviewed": null`. Treat their **ratios** with more suspicion
than their muscles: a transfer ratio is a judgement, and a wrong one opens somebody's first
session at the wrong weight. Reviewed records say when a human checked them.

## Using it

```bash
curl -sO https://raw.githubusercontent.com/herman551/movement-library/main/data/movements.json
```

`data/movements.json` is the whole set, sorted by `id`. `schema/movement.schema.json` is the
contract. Ids are stable: a renamed movement keeps its id and gains an alias.

## Contributing

Corrections are welcome, especially to transfer ratios, which are the field most likely to be
wrong. The one hard rule: **nothing copied from a copyrighted source.** Not descriptions, not
images, not an index of names lifted wholesale from another library. A pull request that
brings in someone else's records, however permissively they appear to be licensed, will be
refused unless the chain of custody is verifiable.

By contributing you agree your contribution is dedicated to the public domain under CC0.
