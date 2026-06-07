# QA — Quiet Tutor Finder

I didn't take the script's word for it. I ran it from a clean output directory and re-derived the answer from the raw CSVs by hand before trusting a single number.

## What I checked

**Nothing got lost.** Every one of the 135 session rows is accounted for: 132 matched to a tutor, 3 sent to the review list, 0 unparseable dates. That's the check that actually matters — if rows silently vanish, a tutor goes quiet and nobody knows. They don't here.

**The two traps in the data both resolve correctly — and the right way.**
- `J. Smith` (Physics) → John Smith. His last real session is 27 May, so he stays active. Miss that match and he looks 37 days quiet — a false alarm.
- `Sarah L.` (Biology) → Sarah Leung, last session 28 May, active. Miss it and she reads 44 days quiet. Also false.

Both were rescued by using the session subject to break the tie between same-surname tutors. That's the difference between a list I'd trust and one I wouldn't.

**`Kevin Tran` is correctly NOT guessed onto Mei Tan.** He's not on the roster, so he goes to the human-review list instead of getting force-matched to a lookalike. I checked why: the name similarity falls below the cutoff *and* the first names don't match — two independent reasons, not luck.

**The five quiet tutors and their day counts recompute exactly:** Hannah Cohen 56d, Aarav Sharma 49d, Aisha Rahman 42d, Mei Tan 35d, Priya Nair 31d. All genuinely past three weeks, sorted longest-quiet first.

## One note worth surfacing

The Tran/Tan rejection clears the bar by a thin margin. It's the first-name check doing most of the work, not the surname similarity. So if a future weekly run sees a near-collision — a typo'd surname, or an abbreviation like `M. Tan` — it could wobble. Not a bug today; the answer is correct. But it's the spot I'd watch first when this runs on next week's data, and it's exactly why the review list exists.

## Verdict

**PASS.** Results are correct, and when the data is ambiguous the script does the safe thing — it hands the call to a person instead of guessing. That's the behavior I want.
