#!/usr/bin/env python3
"""
TMJ Tutoring — Quiet Tutor Finder
=================================

Finds tutors who have gone "quiet" (no session in 3+ weeks) so a human can
check in on them before a parent notices.

Run:
    python3 quiet_tutors.py
    python3 quiet_tutors.py --sessions sessions.csv --tutors tutors.csv --out ./out

Outputs:
    1. A console report (the thing a person actually reads), and
    2. quiet_tutors.csv     — the check-in list, one row per quiet tutor, with tutor_id.
    3. review_unmatched.csv — session names that could NOT be confidently tied to a
                              tutor_id. These are surfaced on purpose, not dropped.
    4. report.html          — a self-contained admin dashboard (no server, no deps).

Dependencies: Python 3 standard library only (csv, datetime, difflib). No pip install.

--- Key decisions (see the note for the short version) ---
* "Today" is 2026-05-29 (the export date, per the brief).
* Quiet  = days since last session >= 21  (i.e. last session on/before 2026-05-08).
           "Three weeks or more" is read as >= 21 days, inclusive of the 21st day.
* Name matching: exact normalized match first; then a structured fuzzy pass that
  understands abbreviated forms ("J. Smith", "Sarah L."). When an abbreviation is
  ambiguous between two roster tutors, the session's SUBJECT breaks the tie
  (the roster carries each tutor's subject). If it still can't be resolved to
  exactly one tutor, the name goes to the review list rather than being guessed.

--- Learning loop: human edits become durable rules (aliases.csv) ---
* When a human resolves a review entry, that decision is persisted in aliases.csv
  and consulted BEFORE fuzzy matching on every later run. A confirmed mapping is
  the highest confidence tier ("confirmed"); a "IGNORE" target suppresses a name
  the human has ruled out (ex-tutor / typo) so it stops cluttering review.
* Each alias records the roster it was confirmed against (roster_fingerprint).
  If a NEWLY added tutor later collides with an alias's name, the alias is treated
  as STALE and re-surfaced for one-time re-confirmation instead of routing blind.
  The learning store yields to roster changes; it never overrides a genuine new
  tutor. Aliases.csv is a deterministic, auditable lookup table — not a model.
"""

from __future__ import annotations

import argparse
import csv
import html
import os
import re
import sys
from collections import defaultdict
from datetime import datetime as _dt
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher

# "Today", per the brief: export is current as of Friday 29 May 2026.
TODAY = date(2026, 5, 29)
QUIET_DAYS = 21  # three weeks

# Default paths: the challenge CSVs ship in ./data so this runs out-of-the-box.
# Resolved relative to this script so it works from any working directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SESSIONS = os.path.join(_HERE, "data", "sessions.csv")
DEFAULT_TUTORS = os.path.join(_HERE, "data", "tutors.csv")
DEFAULT_ALIASES = os.path.join(_HERE, "data", "aliases.csv")

# Special alias target: a name a human has ruled out (ex-tutor, typo, not a real tutor).
IGNORE_ID = "IGNORE"

# Fuzzy thresholds. Names here are short, so we keep these strict to avoid
# pairing genuinely different people (e.g. "Tran" must not become "Tan").
FULL_TOKEN_RATIO = 0.88  # similarity needed to treat two non-initial tokens as the same


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #
@dataclass
class Tutor:
    tutor_id: str
    name: str
    phone: str
    email: str
    subject: str
    first: str = ""
    last: str = ""
    norm: str = ""  # normalized full name

    def __post_init__(self):
        self.norm = normalize(self.name)
        self.first, self.last = split_name(self.name)


@dataclass
class TutorStats:
    tutor: Tutor
    last_session: date | None = None
    session_count: int = 0
    matched_via: set[str] = field(default_factory=set)  # how rows resolved to this tutor


@dataclass
class Alias:
    """A human-confirmed mapping from a messy session name to a tutor_id (or IGNORE)."""
    raw_name: str
    subject: str            # "" = applies to any subject; else used to disambiguate
    tutor_id: str           # a real tutor_id, or IGNORE_ID to suppress the name
    fingerprint: set[str]   # tutor_ids that existed on the roster when this was confirmed
    note: str = ""
    norm: str = ""

    def __post_init__(self):
        self.norm = normalize(self.raw_name)


# --------------------------------------------------------------------------- #
# Normalization helpers
# --------------------------------------------------------------------------- #
def normalize(name: str) -> str:
    """Lowercase, drop punctuation (so 'J.' -> 'j', "O'Connor" -> 'oconnor'), collapse spaces."""
    n = name.strip().lower()
    n = re.sub(r"[.,]", "", n)
    n = n.replace("'", "")
    n = re.sub(r"\s+", " ", n)
    return n


def split_name(name: str) -> tuple[str, str]:
    """Split into (given, surname) on the normalized form. Assumes the last token is the surname."""
    toks = normalize(name).split()
    if not toks:
        return "", ""
    if len(toks) == 1:
        return "", toks[0]
    return toks[0], toks[-1]


def is_initial(token: str) -> bool:
    return len(token) == 1


def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def token_compatible(session_tok: str, roster_tok: str) -> bool:
    """
    Are two name tokens plausibly the same person's name part?
    An initial matches by first letter ('j' ~ 'john'); full tokens match by
    equality or high similarity.
    """
    if not session_tok or not roster_tok:
        return False
    if is_initial(session_tok):
        return roster_tok.startswith(session_tok)
    if is_initial(roster_tok):
        return session_tok.startswith(roster_tok)
    if session_tok == roster_tok:
        return True
    return ratio(session_tok, roster_tok) >= FULL_TOKEN_RATIO


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
@dataclass
class MatchResult:
    tutor: Tutor | None
    # "confirmed" | "exact" | "fuzzy" | "fuzzy+subject" | "ignored" | "unmatched"
    method: str
    reason: str = ""     # human-readable explanation for the review/transparency log


def _fuzzy_candidates(raw_name: str, roster: list[Tutor]) -> list[Tutor]:
    """Roster tutors plausibly named by raw_name: exact normalized, else structured fuzzy."""
    norm = normalize(raw_name)
    exact = [t for t in roster if t.norm == norm]
    if exact:
        return exact
    s_first, s_last = split_name(raw_name)
    out = []
    for t in roster:
        given_ok = token_compatible(s_first, t.first) if (s_first or t.first) else True
        surname_ok = token_compatible(s_last, t.last)
        if given_ok and surname_ok:
            out.append(t)
    return out


def lookup_alias(aliases: list[Alias], raw_name: str, subject: str) -> Alias | None:
    """Find the alias for this name. A subject-specific alias beats a blank-subject one."""
    norm = normalize(raw_name)
    sub = (subject or "").strip().lower()
    subject_hit = blank_hit = None
    for a in aliases:
        if a.norm != norm:
            continue
        if a.subject and a.subject.strip().lower() == sub:
            subject_hit = a
        elif not a.subject:
            blank_hit = a
    return subject_hit or blank_hit


def alias_is_stale(alias: Alias, roster: list[Tutor]) -> tuple[bool, str]:
    """
    L Lawliet's guard: a confirmed alias must yield to roster changes, never override
    a genuinely new tutor. An alias is stale if its target left the roster, OR if a
    tutor added since it was confirmed now plausibly matches the alias's name.
    """
    roster_ids = {t.tutor_id for t in roster}
    if alias.tutor_id != IGNORE_ID and alias.tutor_id not in roster_ids:
        return True, f"target {alias.tutor_id} is no longer on the roster"
    if alias.fingerprint:
        new_ids = roster_ids - alias.fingerprint
        if new_ids:
            new_tutors = [t for t in roster if t.tutor_id in new_ids]
            if _fuzzy_candidates(alias.raw_name, new_tutors):
                return True, (f'newly added tutor(s) {", ".join(sorted(new_ids))} now '
                              f'plausibly match "{alias.raw_name}" — needs re-confirmation')
    return False, ""


def match_session(raw_name: str, subject: str, roster: list[Tutor],
                  aliases: list[Alias] | None = None) -> MatchResult:
    # 0) Human-confirmed alias overrides matching — UNLESS it is stale vs the roster.
    if aliases:
        al = lookup_alias(aliases, raw_name, subject)
        if al is not None:
            stale, why = alias_is_stale(al, roster)
            if not stale:
                if al.tutor_id == IGNORE_ID:
                    note = al.note or "not a tutor"
                    return MatchResult(None, "ignored",
                                       f'"{raw_name}" suppressed by a human: {note}')
                tut = next((t for t in roster if t.tutor_id == al.tutor_id), None)
                if tut is not None:
                    extra = f" — {al.note}" if al.note else ""
                    return MatchResult(tut, "confirmed",
                                       f'"{raw_name}" → {tut.name} ({tut.tutor_id}), '
                                       f'human-confirmed{extra}')
            # Stale alias: fall through to normal matching so it re-enters review for
            # one-time re-confirmation instead of routing to a now-ambiguous target.

    norm = normalize(raw_name)

    # 1) Exact normalized full-name match — the common case.
    exact = [t for t in roster if t.norm == norm]
    if len(exact) == 1:
        return MatchResult(exact[0], "exact")
    if len(exact) > 1:
        # Two roster tutors with identical normalized names: fall through to subject.
        cands = exact
    else:
        # 2) Structured fuzzy pass over (given, surname).
        cands = _fuzzy_candidates(raw_name, roster)

    if not cands:
        return MatchResult(None, "unmatched", f'no roster tutor resembles "{raw_name}"')

    if len(cands) == 1:
        return MatchResult(cands[0], "fuzzy", f'"{raw_name}" -> {cands[0].name} ({cands[0].tutor_id})')

    # 3) Ambiguous: break the tie using the session subject vs each tutor's subject.
    sub = (subject or "").strip().lower()
    by_subject = [t for t in cands if t.subject.strip().lower() == sub]
    if len(by_subject) == 1:
        t = by_subject[0]
        names = ", ".join(c.name for c in cands)
        return MatchResult(
            t, "fuzzy+subject",
            f'"{raw_name}" ambiguous among [{names}]; subject "{subject}" -> {t.name} ({t.tutor_id})',
        )

    names = ", ".join(f"{c.name}/{c.tutor_id}" for c in cands)
    return MatchResult(
        None, "unmatched",
        f'"{raw_name}" ambiguous among [{names}] and subject "{subject}" did not resolve it',
    )


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
def load_tutors(path: str) -> list[Tutor]:
    tutors = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tutors.append(Tutor(
                tutor_id=row["tutor_id"].strip(),
                name=row["name"].strip(),
                phone=row["phone"].strip(),
                email=row["email"].strip(),
                subject=row["subject"].strip(),
            ))
    return tutors


def load_aliases(path: str) -> list[Alias]:
    """Load human-confirmed name overrides. Missing file = no aliases (this is fine)."""
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = (row.get("raw_name") or "").strip()
            if not raw:
                continue
            fp = (row.get("roster_fingerprint") or "").strip()
            fingerprint = {x.strip() for x in fp.split(";") if x.strip()}
            out.append(Alias(
                raw_name=raw,
                subject=(row.get("subject") or "").strip(),
                tutor_id=(row.get("tutor_id") or "").strip(),
                fingerprint=fingerprint,
                note=(row.get("note") or "").strip(),
            ))
    return out


def parse_date(s: str) -> date | None:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
def analyze(sessions_path: str, tutors_path: str, aliases_path: str | None = None):
    roster = load_tutors(tutors_path)
    aliases = load_aliases(aliases_path) if aliases_path else []
    stats = {t.tutor_id: TutorStats(t) for t in roster}

    # Aggregate unmatched/ambiguous raw names for the review list.
    unmatched: dict[str, dict] = defaultdict(lambda: {"count": 0, "reason": "", "subjects": set()})
    # Names a human has explicitly suppressed via an alias (ex-tutor / typo).
    ignored: dict[str, dict] = defaultdict(lambda: {"count": 0, "reason": "", "subjects": set()})
    bad_dates = 0
    # Transparency log: every row that needed a judgment call (not an exact match).
    decisions: dict[tuple, dict] = defaultdict(
        lambda: {"count": 0, "reason": "", "tutor_name": "", "tutor_id": "", "method": ""}
    )
    total_rows = 0

    # Surface any alias that was disabled this run because the roster changed.
    stale_warnings: list[str] = []
    seen_stale: set[str] = set()
    for al in aliases:
        stale, why = alias_is_stale(al, roster)
        if stale and al.raw_name not in seen_stale:
            seen_stale.add(al.raw_name)
            stale_warnings.append(f'"{al.raw_name}": {why}')

    with open(sessions_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total_rows += 1
            raw_name = (row.get("tutor_name") or "").strip()
            subject = (row.get("subject") or "").strip()
            d = parse_date(row.get("date", ""))
            if d is None:
                bad_dates += 1
                continue

            res = match_session(raw_name, subject, roster, aliases)

            if res.method == "ignored":
                g = ignored[raw_name]
                g["count"] += 1
                g["reason"] = res.reason
                g["subjects"].add(subject)
                continue

            if res.tutor is None:
                u = unmatched[raw_name]
                u["count"] += 1
                u["reason"] = res.reason
                u["subjects"].add(subject)
                continue

            st = stats[res.tutor.tutor_id]
            st.session_count += 1
            st.matched_via.add(res.method)
            if st.last_session is None or d > st.last_session:
                st.last_session = d

            if res.method != "exact":
                key = (raw_name, res.tutor.tutor_id, res.method)
                dec = decisions[key]
                dec["count"] += 1
                dec["reason"] = res.reason
                dec["tutor_name"] = res.tutor.name
                dec["tutor_id"] = res.tutor.tutor_id
                dec["method"] = res.method

    return roster, stats, unmatched, bad_dates, decisions, total_rows, ignored, stale_warnings


def days_since(d: date | None) -> int | None:
    return None if d is None else (TODAY - d).days


def is_quiet(st: TutorStats) -> bool:
    if st.last_session is None:
        return True  # roster tutor with zero sessions is quiet by definition
    return (TODAY - st.last_session).days >= QUIET_DAYS


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_quiet_csv(path: str, quiet: list[TutorStats]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "tutor_id", "name", "subject", "phone", "email",
            "last_session_date", "days_since_last_session", "total_sessions", "match_notes",
        ])
        for st in quiet:
            last = st.last_session.isoformat() if st.last_session else "NONE ON RECORD"
            ds = days_since(st.last_session)
            w.writerow([
                st.tutor.tutor_id, st.tutor.name, st.tutor.subject,
                st.tutor.phone, st.tutor.email, last,
                "" if ds is None else ds, st.session_count,
                "+".join(sorted(st.matched_via)) if st.matched_via else "",
            ])


def write_review_csv(path: str, unmatched: dict[str, dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["raw_tutor_name", "sessions_count", "subjects_seen", "why_not_matched"])
        for name, info in sorted(unmatched.items()):
            w.writerow([name, info["count"], "; ".join(sorted(info["subjects"])), info["reason"]])


def print_report(roster, stats, unmatched, bad_dates, outdir, ignored=None, stale_warnings=None):
    ignored = ignored or {}
    stale_warnings = stale_warnings or []
    quiet = sorted(
        (st for st in stats.values() if is_quiet(st)),
        key=lambda s: (days_since(s.last_session) is not None, days_since(s.last_session) or 10**9),
        reverse=True,
    )
    active = [st for st in stats.values() if not is_quiet(st)]

    line = "=" * 72
    print(line)
    print(f"  TMJ TUTORING — QUIET TUTOR CHECK-IN LIST")
    print(f"  As of {TODAY:%A %d %B %Y}  ·  quiet = no session in {QUIET_DAYS}+ days")
    print(line)
    print(f"  Roster: {len(roster)} tutors   |   Active: {len(active)}   |   QUIET: {len(quiet)}")
    print()

    if not quiet:
        print("  No quiet tutors. Everyone has run a session in the last 3 weeks.")
    else:
        print(f"  {'#':>2}  {'ID':<5} {'NAME':<18} {'SUBJECT':<10} {'LAST SEEN':<12} {'QUIET':>6}")
        print("  " + "-" * 66)
        for i, st in enumerate(quiet, 1):
            last = st.last_session.isoformat() if st.last_session else "NEVER"
            ds = days_since(st.last_session)
            quiet_str = "never" if ds is None else f"{ds}d"
            print(f"  {i:>2}  {st.tutor.tutor_id:<5} {st.tutor.name:<18} "
                  f"{st.tutor.subject:<10} {last:<12} {quiet_str:>6}")
        print()
        print("  Contact details for the check-in:")
        for st in quiet:
            print(f"    · {st.tutor.tutor_id}  {st.tutor.name:<18} {st.tutor.phone:<18} {st.tutor.email}")

    if unmatched:
        print()
        print(line)
        print("  ⚠ NEEDS A HUMAN — session names not confidently tied to a tutor_id")
        print(line)
        for name, info in sorted(unmatched.items()):
            subs = ", ".join(sorted(info["subjects"]))
            print(f"    · \"{name}\"  ({info['count']} session(s), subject: {subs})")
            print(f"        why: {info['reason']}")
        print()
        print("  These are surfaced on purpose. They are NOT in the quiet list above and")
        print("  were NOT silently dropped — decide who they are before acting.")

    if ignored:
        print()
        print("  Suppressed by a human (alias rules) — not a tutor / ex-tutor / typo:")
        for name, info in sorted(ignored.items()):
            print(f"    · \"{name}\"  ({info['count']} session(s)) — {info['reason']}")

    if stale_warnings:
        print()
        print("  ⚠ Alias rules disabled this run (roster changed — re-confirm these):")
        for w in stale_warnings:
            print(f"    · {w}")

    if bad_dates:
        print(f"\n  Note: {bad_dates} session row(s) had an unparseable date and were skipped.")

    print()
    print(f"  Written: {os.path.join(outdir, 'quiet_tutors.csv')}")
    print(f"  Written: {os.path.join(outdir, 'review_unmatched.csv')}")
    print(line)
    return quiet


# --------------------------------------------------------------------------- #
# HTML report — a "light UI": one self-contained file, no server, no deps.
# --------------------------------------------------------------------------- #
# How each match method maps to an admin-facing confidence level.
CONFIDENCE = {
    "confirmed": ("Confirmed", "A human confirmed this name maps to this tutor.", "conf-confirmed"),
    "exact": ("High", "Name matched the roster exactly.", "conf-high"),
    "fuzzy": ("Medium", "Matched by name shape (e.g. an initial); only one candidate.", "conf-med"),
    "fuzzy+subject": ("Review", "Name was ambiguous; resolved using the session subject.", "conf-review"),
}


def tutor_confidence(methods: set[str]) -> tuple[str, str]:
    """Overall confidence for a tutor = the weakest method any of their rows used."""
    order = ["fuzzy+subject", "fuzzy", "exact", "confirmed"]  # weakest first
    for m in order:
        if m in methods:
            label, _desc, cls = CONFIDENCE[m]
            return label, cls
    return "—", "conf-none"


def _sev_class(days: int | None) -> str:
    if days is None:
        return "sev-never"
    if days >= 42:
        return "sev-high"
    if days >= 28:
        return "sev-mid"
    return "sev-low"


def write_html_report(path, roster, stats, unmatched, bad_dates, decisions, total_rows, sources,
                      ignored=None, stale_warnings=None):
    ignored = ignored or {}
    stale_warnings = stale_warnings or []
    e = html.escape
    quiet = sorted(
        (st for st in stats.values() if is_quiet(st)),
        key=lambda s: (days_since(s.last_session) is not None, days_since(s.last_session) or 10**9),
        reverse=True,
    )
    active = sorted(
        (st for st in stats.values() if not is_quiet(st)),
        key=lambda s: days_since(s.last_session) or 0,
    )
    n_review = sum(v["count"] for v in unmatched.values())
    n_ignored = sum(v["count"] for v in ignored.values())
    matched_rows = total_rows - n_review - bad_dates - n_ignored
    generated = _dt.now().strftime("%Y-%m-%d %H:%M")

    def badge(label, cls):
        return f'<span class="badge {cls}">{e(label)}</span>'

    # --- Quiet rows ---
    quiet_rows = ""
    for i, st in enumerate(quiet, 1):
        last = st.last_session.isoformat() if st.last_session else "never"
        ds = days_since(st.last_session)
        ds_txt = "never" if ds is None else f"{ds} days"
        conf_label, conf_cls = tutor_confidence(st.matched_via)
        quiet_rows += f"""
        <tr>
          <td class="num">{i}</td>
          <td><code>{e(st.tutor.tutor_id)}</code></td>
          <td class="name">{e(st.tutor.name)}</td>
          <td>{e(st.tutor.subject)}</td>
          <td>{e(last)}</td>
          <td><span class="sev {_sev_class(ds)}">{e(ds_txt)}</span></td>
          <td class="num">{st.session_count}</td>
          <td>{badge(conf_label, conf_cls)}</td>
          <td><a href="tel:{e(st.tutor.phone)}">{e(st.tutor.phone)}</a></td>
          <td><a href="mailto:{e(st.tutor.email)}">{e(st.tutor.email)}</a></td>
        </tr>"""

    # --- Review (needs a human) ---
    review_rows = ""
    for name, info in sorted(unmatched.items()):
        review_rows += f"""
        <tr>
          <td class="name">{e(name)}</td>
          <td class="num">{info['count']}</td>
          <td>{e(', '.join(sorted(info['subjects'])))}</td>
          <td class="reason">{e(info['reason'])}</td>
        </tr>"""
    review_section = f"""
      <h2>⚠ Needs a human <span class="count-pill">{len(unmatched)}</span></h2>
      <p class="sub">Session names that could not be confidently tied to a <code>tutor_id</code>.
         Surfaced on purpose — not in the quiet list, not silently dropped.</p>
      <table>
        <thead><tr><th>Name in log</th><th>Sessions</th><th>Subject(s)</th><th>Why not matched</th></tr></thead>
        <tbody>{review_rows}</tbody>
      </table>""" if unmatched else '<h2>⚠ Needs a human <span class="count-pill ok">0</span></h2><p class="sub">Every session name resolved to a tutor. Nothing waiting on a human.</p>'

    # --- Suppressed (human ruled these out via an alias) ---
    sup_section = ""
    if ignored:
        sup_rows = ""
        for name, info in sorted(ignored.items()):
            sup_rows += f"""
        <tr>
          <td class="name">{e(name)}</td>
          <td class="num">{info['count']}</td>
          <td class="reason">{e(info['reason'])}</td>
        </tr>"""
        sup_section = f"""
      <h2>Suppressed by a human <span class="count-pill">{len(ignored)}</span></h2>
      <p class="sub">Names a human ruled out (ex-tutor, typo, not a real tutor) via an alias rule.
         Counted, not silently dropped — so the conservation check still balances.</p>
      <table>
        <thead><tr><th>Name in log</th><th>Sessions</th><th>Why suppressed</th></tr></thead>
        <tbody>{sup_rows}</tbody>
      </table>"""

    # --- Stale alias warnings (roster changed; rule re-surfaced) ---
    stale_section = ""
    if stale_warnings:
        items = "".join(f"<li>{e(w)}</li>" for w in stale_warnings)
        stale_section = f"""
      <h2 class="warnhead">⚠ Alias rules disabled this run <span class="count-pill warn">{len(stale_warnings)}</span></h2>
      <p class="sub warn">A confirmed alias yields to roster changes — it never overrides a genuinely
         new tutor. These were disabled and re-routed to review for one-time re-confirmation.</p>
      <ul class="warnlist">{items}</ul>"""

    # --- Auto-decisions (transparency log) ---
    dec_rows = ""
    for (raw, tid, method), info in sorted(decisions.items(), key=lambda kv: kv[0][0]):
        _label, _desc, cls = CONFIDENCE.get(method, ("?", "", "conf-none"))
        dec_rows += f"""
        <tr>
          <td class="name">{e(raw)}</td>
          <td>→ {e(info['tutor_name'])} <code>{e(tid)}</code></td>
          <td>{badge(*( (CONFIDENCE[method][0], CONFIDENCE[method][2]) ))}</td>
          <td class="num">{info['count']}</td>
          <td class="reason">{e(info['reason'])}</td>
        </tr>"""
    dec_section = f"""
      <h2>Auto-resolved matches <span class="count-pill">{len(decisions)}</span></h2>
      <p class="sub">Rows where the script made a judgment call instead of an exact name match.
         These keep the affected tutors correctly <em>active</em> — review if you want to be sure.</p>
      <table>
        <thead><tr><th>Name in log</th><th>Resolved to</th><th>Confidence</th><th>Rows</th><th>How</th></tr></thead>
        <tbody>{dec_rows}</tbody>
      </table>""" if decisions else ""

    # --- Active roster (collapsible) ---
    active_rows = ""
    for st in active:
        last = st.last_session.isoformat() if st.last_session else "never"
        ds = days_since(st.last_session)
        conf_label, conf_cls = tutor_confidence(st.matched_via)
        active_rows += f"""
        <tr>
          <td><code>{e(st.tutor.tutor_id)}</code></td>
          <td class="name">{e(st.tutor.name)}</td>
          <td>{e(st.tutor.subject)}</td>
          <td>{e(last)}</td>
          <td class="num">{'' if ds is None else ds}</td>
          <td class="num">{st.session_count}</td>
          <td>{badge(conf_label, conf_cls)}</td>
        </tr>"""

    bad_note = (f'<p class="sub warn">{bad_dates} session row(s) had an unparseable date and were skipped.</p>'
                if bad_dates else "")

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TMJ — Quiet Tutor Report</title>
<style>
  :root {{
    --bg:#0f1115; --panel:#171a21; --line:#272b35; --txt:#e7e9ee; --mut:#9aa3b2;
    --accent:#5b8cff; --green:#3fb950; --amber:#d29922; --red:#f85149;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--txt);
         font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:28px 22px 60px; }}
  header h1 {{ margin:0 0 4px; font-size:22px; letter-spacing:.2px; }}
  header .meta {{ color:var(--mut); font-size:13px; }}
  header .meta code {{ color:var(--txt); }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:22px 0 6px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .card .n {{ font-size:28px; font-weight:700; }}
  .card .l {{ color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.6px; }}
  .card.quiet .n {{ color:var(--red); }}
  .card.active .n {{ color:var(--green); }}
  .card.review .n {{ color:var(--amber); }}
  h2 {{ margin:30px 0 4px; font-size:17px; }}
  .sub {{ color:var(--mut); font-size:13px; margin:0 0 12px; }}
  .sub.warn {{ color:var(--amber); }}
  table {{ width:100%; border-collapse:collapse; background:var(--panel);
           border:1px solid var(--line); border-radius:10px; overflow:hidden; font-size:14px; }}
  th,td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ background:#1b1f27; color:var(--mut); font-weight:600; font-size:12px;
        text-transform:uppercase; letter-spacing:.5px; }}
  tr:last-child td {{ border-bottom:none; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.name {{ font-weight:600; }}
  td.reason {{ color:var(--mut); font-size:12.5px; }}
  code {{ background:#0c0e12; border:1px solid var(--line); border-radius:5px;
          padding:1px 6px; font-size:12.5px; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .badge {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:11.5px; font-weight:600; }}
  .conf-confirmed {{ background:rgba(57,208,216,.16); color:#39d0d8; }}
  .conf-high {{ background:rgba(63,185,80,.15); color:#56d364; }}
  .conf-med {{ background:rgba(91,140,255,.15); color:#79a0ff; }}
  .conf-review {{ background:rgba(210,153,34,.18); color:#e3b341; }}
  .conf-none {{ background:#222; color:var(--mut); }}
  .sev {{ padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600; font-variant-numeric:tabular-nums; }}
  .sev-high {{ background:rgba(248,81,73,.16); color:#ff7b72; }}
  .sev-mid {{ background:rgba(210,153,34,.16); color:#e3b341; }}
  .sev-low {{ background:rgba(91,140,255,.14); color:#79a0ff; }}
  .sev-never {{ background:#222; color:var(--mut); }}
  .count-pill {{ background:#222; color:var(--mut); border-radius:999px; padding:1px 9px;
                 font-size:12px; font-weight:600; vertical-align:middle; }}
  .count-pill.ok {{ background:rgba(63,185,80,.15); color:#56d364; }}
  .count-pill.warn {{ background:rgba(210,153,34,.18); color:#e3b341; }}
  .warnhead {{ color:#e3b341; }}
  .warnlist {{ margin:6px 0 0; padding-left:20px; color:#e3b341; font-size:13px; }}
  .warnlist li {{ margin:3px 0; }}
  details {{ margin-top:8px; }}
  summary {{ cursor:pointer; color:var(--accent); font-size:14px; }}
  .legend {{ color:var(--mut); font-size:12.5px; margin:10px 0 0; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:34px; border-top:1px solid var(--line); padding-top:14px; }}
</style></head>
<body><div class="wrap">
  <header>
    <h1>TMJ Tutoring — Quiet Tutor Check-in</h1>
    <div class="meta">
      Today: <code>{e(TODAY.strftime('%A %d %B %Y'))}</code> ·
      Quiet threshold: <code>≥ {QUIET_DAYS} days</code> ·
      Generated: <code>{e(generated)}</code><br>
      Sources: <code>{e(os.path.basename(sources[0]))}</code> + <code>{e(os.path.basename(sources[1]))}</code>
    </div>
  </header>

  <div class="cards">
    <div class="card"><div class="n">{len(roster)}</div><div class="l">Tutors on roster</div></div>
    <div class="card active"><div class="n">{len(active)}</div><div class="l">Active</div></div>
    <div class="card quiet"><div class="n">{len(quiet)}</div><div class="l">Quiet (need check-in)</div></div>
    <div class="card review"><div class="n">{len(unmatched)}</div><div class="l">Names need a human</div></div>
  </div>
  <p class="legend">Rows processed: {total_rows} &nbsp;=&nbsp; {matched_rows} matched + {n_review} review + {n_ignored} suppressed + {bad_dates} bad dates &nbsp;(conservation check: no silent drops).</p>
  {stale_section}

  <h2>Quiet tutors <span class="count-pill">{len(quiet)}</span></h2>
  <p class="sub">No session in {QUIET_DAYS}+ days, worst first. Every tutor carries their <code>tutor_id</code>.</p>
  <table>
    <thead><tr>
      <th>#</th><th>ID</th><th>Name</th><th>Subject</th><th>Last seen</th>
      <th>Quiet for</th><th>Sessions</th><th>Confidence</th><th>Phone</th><th>Email</th>
    </tr></thead>
    <tbody>{quiet_rows if quiet_rows else '<tr><td colspan="10">No quiet tutors. 🎉</td></tr>'}</tbody>
  </table>
  <p class="legend">
    Confidence: {badge('Confirmed','conf-confirmed')} human-confirmed alias &nbsp;
    {badge('High','conf-high')} exact name match &nbsp;
    {badge('Medium','conf-med')} matched by name shape &nbsp;
    {badge('Review','conf-review')} ambiguous, resolved via subject.
  </p>

  {review_section}

  {sup_section}

  {dec_section}

  <h2>Active tutors</h2>
  <details><summary>Show all {len(active)} active tutors</summary>
  <table style="margin-top:10px">
    <thead><tr><th>ID</th><th>Name</th><th>Subject</th><th>Last seen</th>
      <th>Days ago</th><th>Sessions</th><th>Confidence</th></tr></thead>
    <tbody>{active_rows}</tbody>
  </table></details>
  {bad_note}

  <footer>
    Generated by <code>quiet_tutors.py</code> · Python standard library only ·
    "Quiet" = no session in {QUIET_DAYS}+ days as of {e(TODAY.isoformat())}.
  </footer>
</div></body></html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find quiet TMJ tutors (no session in 3+ weeks).")
    ap.add_argument("--sessions", default=DEFAULT_SESSIONS)
    ap.add_argument("--tutors", default=DEFAULT_TUTORS)
    ap.add_argument("--aliases", default=DEFAULT_ALIASES,
                    help="human-confirmed name overrides (optional; missing file = none)")
    ap.add_argument("--out", default=".", help="output directory for CSVs + HTML report")
    args = ap.parse_args(argv)

    for p in (args.sessions, args.tutors):
        if not os.path.exists(p):
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            return 2

    os.makedirs(args.out, exist_ok=True)
    (roster, stats, unmatched, bad_dates, decisions,
     total_rows, ignored, stale_warnings) = analyze(args.sessions, args.tutors, args.aliases)
    quiet = print_report(roster, stats, unmatched, bad_dates, args.out, ignored, stale_warnings)

    write_quiet_csv(os.path.join(args.out, "quiet_tutors.csv"), quiet)
    write_review_csv(os.path.join(args.out, "review_unmatched.csv"), unmatched)
    html_path = os.path.join(args.out, "report.html")
    write_html_report(html_path, roster, stats, unmatched, bad_dates,
                      decisions, total_rows, (args.sessions, args.tutors),
                      ignored, stale_warnings)
    print(f"  Written: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
