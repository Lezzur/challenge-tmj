# TMJ Quiet-Tutor Finder — Note

**What I decided**

- **Today = 2026-05-29** (the export date). **Quiet = ≥ 21 days since last session** (last session on/before 8 May). I read "three weeks or more" as inclusive of day 21.
- **Name matching:** exact normalized match first (case/punctuation/whitespace-insensitive, so `O'Connor` and `J.` normalize cleanly), then a given/surname match that allows initials. When an abbreviation is ambiguous between two real tutors, **the session's subject breaks the tie** — the roster carries each tutor's subject:
  - `J. Smith` (Physics) → John Smith **T004**, not Jane Smith T005
  - `Sarah L.` (Biology) → Sarah Leung **T003**, not Sarah Lee T002
  Both look quiet by full name alone — their abbreviated sessions run to late May. Disambiguating kills two false alarms.
- **`Kevin Tran`** isn't on the roster (no tutor_id). I don't guess him onto the lookalike "Mei Tan" — he goes to a review list, **surfaced, not dropped**.
- A roster tutor with zero sessions would count as quiet (none here).

**Result — 5 quiet:** Hannah Cohen T015 (56d), Aarav Sharma T001 (49d), Aisha Rahman T012 (42d), Mei Tan T006 (35d), Priya Nair T008 (31d).

**Before production I'd confirm:** (1) the exact boundary (≥21 vs >21) and the timezone of "today"; (2) whether a stable `tutor_id` can be stamped on sessions at source — fuzzy name-matching is a stopgap, not a foundation; (3) how to treat unmatched names like Kevin Tran (typo? ex-tutor? missing roster row?).
