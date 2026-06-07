# Form answers

**Q1 — If we ran this automatically every week, what would you watch out for?**

The fuzzy name-matching. It's a stopgap, not a foundation — it works on today's
data because the subject field happens to break the ties (`J. Smith` Physics →
John Smith, not Jane Smith). But a new tutor whose name collides with an existing
one, a subject typo, or a new abbreviation pattern could silently misattribute a
session and make a quiet tutor look active (or vice-versa). I'd watch the
"needs a human" / review count each week: if it grows or a name keeps reappearing
there (like `Kevin Tran`), that's the signal the roster is drifting from reality.
Also watch the "today" boundary and timezone — run it on a fixed schedule so the
21-day cutoff is consistent, and decide once whether quiet is ≥21 or >21 days.
The real fix is stamping a stable `tutor_id` on sessions at the source so we
never have to guess.

**Q2 — What did you choose not to build, and why?**

- **No fuzzy-match auto-resolution of unknowns.** `Kevin Tran` isn't on the
  roster; I refused to guess him onto the lookalike "Mei Tan." Wrong guesses are
  worse than an honest "a human should look at this," so unknowns are surfaced,
  never silently dropped or auto-assigned.
- **No external dependencies.** Standard library only — no pandas, no rapidfuzz.
  It runs anywhere with zero `pip install`, which matters more than a marginally
  smarter matcher for a 135-row weekly job.
- **No database, scheduler, or notifications.** The brief is "produce an
  actionable list," so I built exactly that plus a self-contained HTML view. Cron,
  email/SMS send, and persistence are easy to add once someone owns the schedule —
  building them now would be guessing at requirements I don't have yet.
