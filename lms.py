"""Read-only deadline sync from a school's calendar feed.

Canvas, Blackboard, Moodle and friends all publish a personal iCalendar (ICS)
feed containing your assignment due dates. Subscribing to that feed is the
officially supported, read-only way to see your deadlines somewhere else — no
password, no OAuth app, no scraping, and nothing EchoPad can ever write back to
your LMS. You paste one URL; EchoPad fetches it and reads the dates.

The feed URL is a bearer credential: anyone holding it can read your calendar,
so it's stored locally alongside your notes and never sent anywhere but your
school's own server.
"""
import hashlib
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

USER_AGENT = "EchoPad/0.5 (+https://github.com/br24563/Echo-pad)"
FETCH_TIMEOUT_SECONDS = 20
# Generous for a term of assignments, small enough that a wrong URL pointing at
# something huge can't exhaust memory.
MAX_FEED_BYTES = 12 * 1024 * 1024
# Safety rails on recurrence expansion, so a pathological RRULE can't spin.
MAX_OCCURRENCES_PER_EVENT = 200
MAX_RECURRENCE_STEPS = 2000

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")

# Where each platform hides its calendar feed. Shown verbatim in the UI, so
# these are worded as instructions to the student.
PROVIDERS = {
    "Canvas": {
        "help": (
            "In Canvas, open **Calendar** in the left sidebar, then click "
            "**Calendar Feed** at the bottom right of the calendar sidebar. Copy the "
            "`.ics` link it shows you."
        ),
        "example": "https://yourschool.instructure.com/feeds/calendars/user_ABC123.ics",
    },
    "Blackboard": {
        "help": (
            "In Blackboard, open **Calendar**, then look for **Get External Calendar "
            "Link** (Ultra) or the **iCalendar / Share** option (Original) and copy the "
            "link. If you don't see one, your institution may have the feed disabled — "
            "ask IT, or add the deadlines manually below."
        ),
        "example": "https://blackboard.yourschool.edu/webapps/calendar/calendarFeed/…/learn.ics",
    },
    "Moodle": {
        "help": (
            "In Moodle, open **Calendar**, click **Export calendar**, choose "
            "*All events* and a date range, then use **Get calendar URL** rather than "
            "downloading the file."
        ),
        "example": "https://moodle.yourschool.edu/calendar/export_execute.php?userid=…",
    },
    "Google Calendar": {
        "help": (
            "If your deadlines already land in Google Calendar, open **Settings → "
            "Settings for my calendars → <calendar> → Integrate calendar** and copy the "
            "**Secret address in iCal format**."
        ),
        "example": "https://calendar.google.com/calendar/ical/…/basic.ics",
    },
    "Other / Generic ICS": {
        "help": (
            "Any standard iCalendar (`.ics`) feed URL works here — including a link "
            "your department publishes, or one produced by a third-party bridge."
        ),
        "example": "https://example.edu/path/to/calendar.ics",
    },
}

# Gradescope has no official per-student calendar feed, so there is nothing to
# subscribe to. Shown in the UI so the limitation is stated rather than implied.
GRADESCOPE_NOTE = (
    "**Gradescope** doesn't publish a personal calendar feed, so it can't be connected "
    "directly. Two things usually cover it:\n\n"
    "1. **Most courses run Gradescope through Canvas/Blackboard**, which mirrors the "
    "assignment into the LMS — in which case it's already in the feed above.\n"
    "2. If a Gradescope-only assignment is missing, **add it manually** below. It'll "
    "then behave like any other deadline.\n\n"
    "EchoPad deliberately doesn't ask for your Gradescope password to scrape the site: "
    "that would mean storing your login, and it would break the moment their page "
    "changes."
)


class FeedError(Exception):
    """A feed couldn't be fetched or read, with a message meant for the user."""


def _calendar_parser():
    """Import icalendar on demand.

    app.py imports this module unconditionally, so a module-level import would
    make one missing optional dependency take down note-taking entirely rather
    than just disabling calendar sync.
    """
    try:
        from icalendar import Calendar
    except ImportError:
        raise FeedError(
            "Reading calendar feeds needs the `icalendar` package. Install it with "
            "`pip install icalendar` (or use the Docker launcher, which includes it)."
        )
    return Calendar


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def normalize_feed_url(url: str) -> str:
    """Clean up a pasted calendar URL.

    Calendar links are often handed out as `webcal://`, which is just HTTPS with
    a different scheme so the OS opens a calendar app. Anything that isn't
    http(s) is refused outright — a feed URL must never be able to make EchoPad
    read a local file.
    """
    cleaned = (url or "").strip().strip("<>\"'")
    if not cleaned:
        raise FeedError("Enter a calendar feed URL.")
    if any(char.isspace() for char in cleaned):
        raise FeedError("That URL contains a space — it may have been copied incompletely.")

    # Any scheme-like prefix must be one we allow. Checking for "://" alone isn't
    # enough: data:, javascript: and mailto: have no slashes, and would otherwise
    # be silently turned into "https://data:…" rather than refused.
    scheme_match = _SCHEME_RE.match(cleaned)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme in ("webcal", "webcals"):
            cleaned = "https://" + cleaned[scheme_match.end():].lstrip("/")
        elif scheme not in ("http", "https"):
            raise FeedError(
                f"`{scheme}:` links aren't supported — paste the http(s) or webcal "
                "calendar feed URL from your LMS."
            )
    else:
        cleaned = "https://" + cleaned

    parts = urllib.parse.urlsplit(cleaned)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FeedError("That doesn't look like a calendar feed URL.")
    return cleaned


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_ics(url: str, timeout: int = FETCH_TIMEOUT_SECONDS,
              max_bytes: int = MAX_FEED_BYTES) -> bytes:
    """Download a calendar feed, failing with an explainable message."""
    url = normalize_feed_url(url)
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/calendar, text/plain, */*",
    })

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # Read one byte past the cap so an oversized feed is detected rather
            # than silently truncated into a confusing parse error.
            payload = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise FeedError(
                f"The school's server refused the request ({exc.code}). Calendar feed "
                "URLs expire when you reset them in your LMS — generate a fresh one and "
                "paste it again."
            )
        if exc.code == 404:
            raise FeedError("That URL returned 404 — double-check you copied all of it.")
        raise FeedError(f"The server returned an error ({exc.code} {exc.reason}).")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise FeedError(f"The server didn't respond within {timeout} seconds.")
        if isinstance(reason, ssl.SSLError):
            raise FeedError(f"Couldn't establish a secure connection ({reason}).")
        raise FeedError(f"Couldn't reach that address ({reason}).")
    except (TimeoutError, socket.timeout):
        raise FeedError(f"The server didn't respond within {timeout} seconds.")
    except OSError as exc:
        raise FeedError(f"Network error while fetching the feed ({exc}).")

    if len(payload) > max_bytes:
        raise FeedError(
            f"That feed is larger than {max_bytes // (1024 * 1024)} MB, which is far bigger "
            "than a class calendar — check the URL points at a calendar feed."
        )
    if not payload.strip():
        raise FeedError("The server returned an empty response.")
    if b"BEGIN:VCALENDAR" not in payload[:8192].upper():
        raise FeedError(
            "That URL didn't return a calendar. Make sure you copied the *feed* link "
            "(ending in `.ics`, or a `webcal://` link) rather than the calendar web page."
        )
    return payload


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _as_utc(value, all_day_end_of_day: bool = False):
    """Normalize an ICS date/datetime to an aware UTC datetime.

    Naive values are read as local time — that's what a feed without timezone
    information means in practice, since the student's machine sits in the same
    timezone as their campus far more often than not.
    """
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        # An all-day assignment is due by the end of that day, not 00:00.
        moment = datetime.combine(value, time(23, 59) if all_day_end_of_day else time(0, 0))
    else:
        return None

    if moment.tzinfo is None:
        moment = moment.astimezone()  # interpret as local
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _synthetic_uid(summary: str, when_iso: str) -> str:
    """A stable key for a feed entry that has no UID of its own.

    Deliberately a digest rather than hash(): Python randomizes string hashing
    per process, so a hash-derived key would change on every restart. The row
    would then look like a different entry each launch — losing whatever the
    student had ticked off on it.
    """
    digest = hashlib.sha1(f"{summary}|{when_iso}".encode("utf-8")).hexdigest()[:16]
    return f"echopad-{digest}"


_COURSE_PATTERNS = (
    re.compile(r"\[([^\[\]]{2,40})\]\s*$"),   # Canvas: "Problem Set 4 [BIO 201]"
    re.compile(r"\(([^()]{2,40})\)\s*$"),      # "Essay Draft (ENG 105)"
)


def split_course(summary: str):
    """Pull a trailing course code out of an event title, if there is one.

    Canvas appends `[Course Name]`; several other platforms use parentheses.
    Returns (title, course) with course "" when nothing looks like a code.
    """
    text = (summary or "").strip()
    for pattern in _COURSE_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            title = text[:match.start()].strip(" -–—:")
            if title and candidate:
                return title, candidate
    return text, ""


_ASSIGNMENT_HINTS = re.compile(
    r"assignment|quiz|exam|due|submit|homework|problem set|pset|lab report|essay|"
    r"midterm|final|project|discussion|reading response",
    re.IGNORECASE,
)


def classify(component_name: str, uid: str, summary: str) -> str:
    """"assignment" for things you hand in, "event" for lectures and the like."""
    if component_name == "VTODO":
        return "assignment"
    if "assignment" in (uid or "").lower() or "quiz" in (uid or "").lower():
        return "assignment"      # Canvas encodes the type in its UIDs
    if _ASSIGNMENT_HINTS.search(summary or ""):
        return "assignment"
    return "event"


def _rrule_occurrences(start: datetime, rrule, window_start: datetime, window_end: datetime):
    """Expand a simple recurrence rule into occurrences inside the window.

    Covers the FREQ/INTERVAL/COUNT/UNTIL/BYDAY subset that class schedules
    actually use. Anything more exotic (BYSETPOS, BYMONTHDAY lists, …) falls
    back to the first occurrence rather than guessing wrong.
    """
    def first(key, default=None):
        values = rrule.get(key)
        if not values:
            return default
        return values[0] if isinstance(values, list) else values

    freq = str(first("FREQ", "") or "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return [start]

    try:
        interval = max(1, int(first("INTERVAL", 1)))
    except (TypeError, ValueError):
        interval = 1
    try:
        count = int(first("COUNT")) if first("COUNT") is not None else None
    except (TypeError, ValueError):
        count = None
    # A date-only UNTIL bounds the whole day, so read it as end-of-day rather
    # than midnight — otherwise a legitimate final occurrence gets dropped.
    until_raw = first("UNTIL")
    until = _as_utc(until_raw, all_day_end_of_day=not isinstance(until_raw, datetime))
    bydays = [_WEEKDAYS[str(d).upper()[-2:]] for d in (rrule.get("BYDAY") or [])
              if str(d).upper()[-2:] in _WEEKDAYS]

    occurrences, emitted, steps = [], 0, 0
    cursor = start

    while steps < MAX_RECURRENCE_STEPS and emitted < MAX_OCCURRENCES_PER_EVENT:
        steps += 1

        if freq == "WEEKLY" and bydays:
            week_start = cursor - timedelta(days=cursor.weekday())
            candidates = [week_start + timedelta(days=offset) for offset in sorted(bydays)]
            candidates = [c for c in candidates if c >= start]
        else:
            candidates = [cursor]

        for candidate in candidates:
            if until and candidate > until:
                return occurrences
            if count is not None and emitted >= count:
                return occurrences
            emitted += 1
            if candidate > window_end:
                return occurrences
            if candidate >= window_start:
                occurrences.append(candidate)
            if len(occurrences) >= MAX_OCCURRENCES_PER_EVENT:
                return occurrences

        if cursor > window_end:
            break

        if freq == "DAILY":
            cursor += timedelta(days=interval)
        elif freq == "WEEKLY":
            cursor += timedelta(weeks=interval)
        elif freq == "MONTHLY":
            month_index = cursor.month - 1 + interval
            year = cursor.year + month_index // 12
            month = month_index % 12 + 1
            day = min(cursor.day, _days_in_month(year, month))
            cursor = cursor.replace(year=year, month=month, day=day)
        else:  # YEARLY
            year = cursor.year + interval
            day = min(cursor.day, _days_in_month(year, cursor.month))
            cursor = cursor.replace(year=year, day=day)

    return occurrences


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        following = date(year + 1, 1, 1)
    else:
        following = date(year, month + 1, 1)
    return (following - date(year, month, 1)).days


def parse_ics(data, window_start: datetime = None, window_end: datetime = None):
    """Turn a calendar feed into deadline records.

    Returns (deadlines, warnings). Each deadline is a dict ready for the
    database: uid, title, course, due_at (UTC ISO), all_day, kind, url,
    description. Individual malformed events are skipped and counted in
    `warnings` rather than failing the whole sync.
    """
    now = datetime.now(timezone.utc)
    window_start = window_start or (now - timedelta(days=30))
    window_end = window_end or (now + timedelta(days=365))

    if isinstance(data, str):
        data = data.encode("utf-8", "replace")

    calendar_class = _calendar_parser()
    try:
        calendar = calendar_class.from_ical(data)
    except Exception as exc:
        raise FeedError(f"That calendar couldn't be read ({exc}).")

    deadlines, warnings, skipped = [], [], 0
    for component in calendar.walk():
        if component.name not in ("VEVENT", "VTODO"):
            continue
        try:
            raw = component.get("DUE") if component.name == "VTODO" else None
            raw = raw if raw is not None else component.get("DTSTART")
            if raw is None:
                raw = component.get("DUE")
            if raw is None:
                skipped += 1
                continue

            value = raw.dt
            all_day = isinstance(value, date) and not isinstance(value, datetime)
            when = _as_utc(value, all_day_end_of_day=all_day)
            if when is None:
                skipped += 1
                continue

            summary = str(component.get("SUMMARY") or "").strip() or "(untitled)"
            title, course = split_course(summary)
            uid = str(component.get("UID") or "").strip()
            description = str(component.get("DESCRIPTION") or "").strip()
            if description.lower() == "none":
                description = ""
            url = str(component.get("URL") or "").strip()
            kind = classify(component.name, uid, summary)

            rrule = component.get("RRULE")
            moments = (_rrule_occurrences(when, rrule, window_start, window_end)
                       if rrule else ([when] if window_start <= when <= window_end else []))

            for index, moment in enumerate(moments):
                # A recurring event needs a distinct key per occurrence, or each
                # one would overwrite the last in the index.
                base_uid = uid or _synthetic_uid(summary, _iso(when))
                occurrence_uid = base_uid if len(moments) == 1 and not rrule else f"{base_uid}#{_iso(moment)}"
                deadlines.append({
                    "uid": occurrence_uid,
                    "title": title,
                    "course": course,
                    "due_at": _iso(moment),
                    "all_day": bool(all_day),
                    "kind": kind,
                    "url": url,
                    "description": description[:2000],
                })
        except Exception:
            skipped += 1  # one bad event must not lose the rest of the feed
            continue

    if skipped:
        warnings.append(
            f"{skipped} entr{'y' if skipped == 1 else 'ies'} in the feed couldn't be read "
            "and were skipped."
        )
    if not deadlines and not skipped:
        warnings.append(
            "The feed was read successfully but contained no dates in the next year. "
            "If your term hasn't been published yet, try syncing again later."
        )

    deadlines.sort(key=lambda item: item["due_at"])
    return deadlines, warnings


def fetch_and_parse(url: str, window_start: datetime = None, window_end: datetime = None):
    """Fetch a feed and parse it in one step."""
    return parse_ics(fetch_ics(url), window_start=window_start, window_end=window_end)
