# TMJ Tutoring — Quiet-Tutor Finder

Finds tutors who haven't run a session in **3+ weeks** so an admin can check in on
them. Reads two CSVs, reconciles the messy names between them, and produces a
console report, an admin HTML dashboard, and two CSV artifacts.

## Run it

No dependencies — Python 3 standard library only. No `pip install`.

```bash
python3 quiet_tutors.py --out ./out
```

Optional flags:

```bash
python3 quiet_tutors.py \
  --sessions path/to/sessions.csv \
  --tutors   path/to/tutors.csv \
  --out      ./out
```

## What it produces

| File | What it is |
|------|------------|
| console output | The check-in list + contact details + anything needing a human |
| `out/report.html` | Self-contained admin dashboard (open in any browser) |
| `out/quiet_tutors.csv` | The quiet list with tutor_id + contact details |
| `out/review_unmatched.csv` | Session names that couldn't be tied to a tutor_id |

## The UI

`report.html` is a single self-contained file (inline CSS, no server, no JS deps).
It shows:

- **Summary cards** — roster size, active, quiet, needs-review counts.
- **Quiet tutors** — ranked by days silent, severity-coloured, with a confidence
  badge and tap-to-call / email links for each.
- **Needs a human** — session names not confidently matched to a tutor_id,
  surfaced (never silently dropped).
- **Auto-resolved matches** — a transparency log of every non-exact match the
  script made and *why*, so a human can audit the fuzzy calls.
- **Active tutors** — collapsed by default.

![report](docs/report.png)

## How matching works

Names don't line up cleanly between the two files (`J. Smith`, `Sarah L.`,
`O'Connor`). The script matches in three tiers, weakest tier sets the confidence:

1. **Exact** (normalised: case/punctuation/whitespace-insensitive) → **High**
2. **Structured fuzzy** on given/surname, allowing initials → **Medium**
3. **Subject tie-break** when an abbreviation is ambiguous between two real tutors
   → **Review** — e.g. `J. Smith` (Physics) → John Smith T004, not Jane Smith T005.

Anything that matches nothing confidently (e.g. `Kevin Tran`, not on the roster)
goes to the review list, not the quiet list.

**Conservation guarantee:** every session row is accounted for — matched, sent to
review, or flagged as a bad date. Nothing is silently dropped.

## Result on the provided data

5 quiet tutors as of Fri 29 May 2026 (quiet = 21+ days):

| # | ID | Name | Last seen | Days |
|---|----|----|----|----|
| 1 | T015 | Hannah Cohen | 2026-04-03 | 56 |
| 2 | T001 | Aarav Sharma | 2026-04-10 | 49 |
| 3 | T012 | Aisha Rahman | 2026-04-17 | 42 |
| 4 | T006 | Mei Tan | 2026-04-24 | 35 |
| 5 | T008 | Priya Nair | 2026-04-28 | 31 |

See [`NOTE.md`](NOTE.md) for the decisions and what I'd confirm before production.
