"""Storage for crowd reports and reviews from people on campus (SQLite file: data/campusense.db).

There is no login. "who" is a random id made for each browser session, so cooldowns work,
but it is never linked to a name, a register number or a location. Coordinates are not stored.
"""
import os
import re
import sqlite3
import time
from contextlib import closing

DB_PATH = "data/campusense.db"
LEVELS = ["Low", "Medium", "High"]

MIN_REPORTS = 2          # distinct people needed before reports override the model (use 3 or more in real life)
WINDOW_MIN = 30          # a crowd report counts for this many minutes
COOLDOWN_MIN = 15        # one crowd report per person (browser session) per place per this many minutes
MAX_PLACE_REPORTS = 12   # at most this many reports per place per cooldown window, from everyone (anti-spam)
MAX_COMMENT = 200        # characters
DAILY_REVIEW_LIMIT = 10  # reviews per person (browser session) per day


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with closing(_conn()) as c, c:
        c.executescript(
            """
            create table if not exists reports(
                id integer primary key autoincrement, ts integer not null,
                place text not null, level integer not null, who text not null);
            create index if not exists ix_reports on reports(place, ts);
            create table if not exists reviews(
                id integer primary key autoincrement, ts integer not null,
                place text not null, rating integer, comment text not null, who text not null);
            create index if not exists ix_reviews on reviews(place, ts);
            """
        )


def clean_text(s, n=MAX_COMMENT):
    """Remove control characters, collapse spaces, cap the length."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def add_report(place, level, who, now=None):
    now = int(now or time.time())
    if level not in (0, 1, 2):
        return False, "Pick Low, Medium or High."
    with closing(_conn()) as c, c:
        last = c.execute("select max(ts) from reports where who=? and place=?", (who, place)).fetchone()[0]
        if last and now - last < COOLDOWN_MIN * 60:
            wait = COOLDOWN_MIN - (now - last) // 60
            return False, f"You already reported {place} recently. You can report again in about {wait} min."
        busy = c.execute("select count(*) from reports where place=? and ts>?", (place, now - COOLDOWN_MIN * 60)).fetchone()[0]
        if busy >= MAX_PLACE_REPORTS:
            return False, f"Lots of reports for {place} just now. Please try again in a few minutes."
        c.execute("insert into reports(ts, place, level, who) values (?,?,?,?)", (now, place, level, who))
    return True, f"Thanks! Your report is live for {WINDOW_MIN} minutes."


def add_review(place, rating, comment, who, now=None):
    now = int(now or time.time())
    comment = clean_text(comment)
    if rating is not None and rating not in (1, 2, 3, 4, 5):
        return False, "Rating must be 1 to 5."
    if rating is None and not comment:
        return False, "Add a rating or a comment."
    with closing(_conn()) as c, c:
        day = now - 86400
        if c.execute("select count(*) from reviews where who=? and ts>?", (who, day)).fetchone()[0] >= DAILY_REVIEW_LIMIT:
            return False, "Daily review limit reached. Try again tomorrow."
        if c.execute("select count(*) from reviews where who=? and place=? and ts>?", (who, place, day)).fetchone()[0]:
            return False, f"You already posted about {place} today."
        c.execute("insert into reviews(ts, place, rating, comment, who) values (?,?,?,?,?)",
                  (now, place, rating, comment, who))
    return True, "Thanks for sharing!"


def live_levels(now=None):
    """{place: {'level', 'count', 'mins_ago'}} for places with enough fresh, distinct-person reports."""
    now = int(now or time.time())
    with closing(_conn()) as c:
        rows = c.execute("select place, level, who, ts from reports where ts>? order by ts desc",
                         (now - WINDOW_MIN * 60,)).fetchall()
    latest = {}  # newest report per (place, person)
    for r in rows:
        latest.setdefault((r["place"], r["who"]), r)
    per_place = {}
    for (place, _), r in latest.items():
        per_place.setdefault(place, []).append(r)
    out = {}
    for place, rs in per_place.items():
        if len(rs) >= MIN_REPORTS:
            mean = sum(r["level"] for r in rs) / len(rs)
            out[place] = {"level": min(2, int(mean + 0.5)), "count": len(rs),
                          "mins_ago": (now - max(r["ts"] for r in rs)) // 60}
    return out


def recent_reports(limit=8, now=None):
    now = int(now or time.time())
    with closing(_conn()) as c:
        rows = c.execute("select place, level, ts from reports where ts>? order by ts desc limit ?",
                         (now - WINDOW_MIN * 60, limit)).fetchall()
    return [{"place": r["place"], "level": r["level"], "mins_ago": (now - r["ts"]) // 60} for r in rows]


def review_stats():
    with closing(_conn()) as c:
        rows = c.execute("select place, avg(rating) a, count(rating) n from reviews "
                         "where rating is not null group by place").fetchall()
    return {r["place"]: (r["a"], r["n"]) for r in rows}


def recent_reviews(limit=6):
    with closing(_conn()) as c:
        rows = c.execute("select place, rating, comment, ts from reviews order by ts desc limit ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def community_context(now=None):
    """Plain-text summary of reports and reviews for the chatbot prompt (unverified data)."""
    now = int(now or time.time())
    lines = []
    for place, v in live_levels(now).items():
        lines.append(f"- {place}: people on campus report {LEVELS[v['level']]} crowd "
                     f"({v['count']} reports, latest {v['mins_ago']} min ago)")
    for place, (avg, n) in review_stats().items():
        lines.append(f"- {place}: average rating {avg:.1f}/5 from {n} review{'s' if n != 1 else ''}")
    for r in recent_reviews(5):
        if r["comment"]:
            lines.append(f"- Comment about {r['place']}: '{r['comment'].replace(chr(34), chr(39))}'")
    return "\n".join(lines) if lines else "No reports or reviews yet."