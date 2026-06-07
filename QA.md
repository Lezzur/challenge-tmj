# QA — independent review (L Lawliet)

**Verdict: PASS.** I ran it clean and checked the numbers against the raw data myself. It holds up.

What I confirmed:

Nothing falls through the cracks. All 135 sessions are accounted for — 132 matched to a tutor, 3 sent to review, none with broken dates. That's the check that actually matters: if rows quietly vanish, a tutor goes silent and you never find out. Doesn't happen here.

The two tricky names both land right, and they land in the way that keeps the tutor *off* the quiet list:
- "J. Smith" on a Physics session is John Smith — last taught 27 May, so he's active. Miss that and he'd look 37 days quiet for no reason.
- "Sarah L." on Biology is Sarah Leung — last taught 28 May, active. Same deal: miss it and she's a false 44-day alarm.

Both got sorted out by using the subject to tell the similar names apart. That's the difference between a list I'd act on and one I wouldn't.

Kevin Tran does NOT get jammed onto "Mei Tan" just because they look alike. He's not on the roster, so he goes to review instead of a wrong guess. I checked why — the names aren't close enough *and* the first names don't match, so it fails two separate ways.

The five quiet tutors all check out, day counts and all — Hannah 56, Aarav 49, Aisha 42, Mei 35, Priya 31, longest first.

One thing to watch, not a problem today: the Kevin Tran / Mei Tan call is close. It's the first-name check carrying it, not the surname. So if next week's file has a typo or an abbreviation that lands near a real name, that's the first place it could wobble. Tony already flagged name drift as the top weekly risk — this is just the concrete example.

Ship it. Results are right, and when it's not sure, it asks a human instead of guessing.
