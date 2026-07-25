"""LMS calendar feed parsing, URL handling, and deadline storage."""
from datetime import datetime, timedelta, timezone

import pytest

import lms


def ics(*lines):
    """Assemble a feed with CRLF line endings, as RFC 5545 requires."""
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//EN",
                        *lines, "END:VCALENDAR"]).encode("utf-8")


WINDOW_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2027, 1, 1, tzinfo=timezone.utc)


def parse(*lines):
    return lms.parse_ics(ics(*lines), window_start=WINDOW_START, window_end=WINDOW_END)


# ---------------------------- URL normalization ----------------------------

@pytest.mark.parametrize("raw,expected", [
    ("webcal://school.edu/f.ics", "https://school.edu/f.ics"),
    ("WEBCAL://school.edu/f.ics", "https://school.edu/f.ics"),
    ("webcals://school.edu/f.ics", "https://school.edu/f.ics"),
    ("https://school.edu/f.ics", "https://school.edu/f.ics"),
    ("http://school.edu/f.ics", "http://school.edu/f.ics"),
    ("  https://school.edu/f.ics  ", "https://school.edu/f.ics"),
    ("<https://school.edu/f.ics>", "https://school.edu/f.ics"),
    ("school.edu/f.ics", "https://school.edu/f.ics"),
])
def test_normalize_feed_url(raw, expected):
    assert lms.normalize_feed_url(raw) == expected


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://school.edu/f.ics",
    # These have no "://", so a naive check waves them through and they become
    # "https://data:…" instead of being refused.
    "data:text/calendar,BEGIN:VCALENDAR",
    "javascript:alert(1)",
    "mailto:someone@school.edu",
])
def test_rejects_non_http_schemes(bad):
    """A pasted feed URL must never be able to make EchoPad read local files or
    anything else that isn't a web request."""
    with pytest.raises(lms.FeedError):
        lms.normalize_feed_url(bad)


def test_rejects_a_scheme_with_no_host():
    with pytest.raises(lms.FeedError):
        lms.normalize_feed_url("https://")


def test_rejects_empty_and_spaced_urls():
    with pytest.raises(lms.FeedError):
        lms.normalize_feed_url("   ")
    with pytest.raises(lms.FeedError):
        lms.normalize_feed_url("https://school.edu/a b.ics")


# ------------------------------ core parsing ------------------------------

def test_parses_a_canvas_style_assignment():
    found, warnings = parse(
        "BEGIN:VEVENT",
        "UID:event-assignment-98765",
        "DTSTART:20260812T235900Z",
        "SUMMARY:Problem Set 4 [BIO 201]",
        "DESCRIPTION:Submit online. Late work loses 10%\\, per day.",
        "URL:https://school.instructure.com/courses/1/assignments/2",
        "END:VEVENT",
    )
    assert warnings == []
    assert len(found) == 1
    item = found[0]
    assert item["title"] == "Problem Set 4"
    assert item["course"] == "BIO 201"          # pulled out of the summary
    assert item["due_at"] == "2026-08-12T23:59:00+00:00"
    assert item["all_day"] is False
    assert item["kind"] == "assignment"
    assert item["url"].endswith("/assignments/2")
    assert "10%, per day" in item["description"]  # escaping undone


def test_parses_all_day_entry_as_end_of_day():
    """An all-day assignment is due by the end of that day, not midnight."""
    found, _ = parse(
        "BEGIN:VEVENT", "UID:allday-1", "DTSTART;VALUE=DATE:20260815",
        "SUMMARY:Essay Draft [ENG 105]", "END:VEVENT",
    )
    assert found[0]["all_day"] is True
    local_due = datetime.fromisoformat(found[0]["due_at"]).astimezone()
    assert (local_due.hour, local_due.minute) == (23, 59)
    assert local_due.date().isoformat() == "2026-08-15"


def test_converts_tzid_times_to_utc():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:tz-1",
        "DTSTART;TZID=America/New_York:20260812T235900",
        "SUMMARY:Lab Report 2", "END:VEVENT",
    )
    # 23:59 EDT is 03:59 UTC the following day
    assert found[0]["due_at"] == "2026-08-13T03:59:00+00:00"


def test_handles_folded_lines():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:fold-1", "DTSTART:20260901T120000Z",
        "SUMMARY:A title long enough that the feed folds it across two separate",
        " lines per the spec",
        "END:VEVENT",
    )
    assert found[0]["title"].endswith("lines per the spec")


def test_reads_vtodo_due_dates():
    """Some platforms publish assignments as VTODO with DUE rather than VEVENT."""
    found, _ = parse(
        "BEGIN:VTODO", "UID:todo-1", "DUE:20260820T050000Z",
        "SUMMARY:Reading Response 3", "END:VTODO",
    )
    assert found[0]["due_at"] == "2026-08-20T05:00:00+00:00"
    assert found[0]["kind"] == "assignment"


def test_classifies_lectures_as_events_and_work_as_assignments():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:e1", "DTSTART:20260902T140000Z",
        "SUMMARY:CS 101 Lecture", "END:VEVENT",
        "BEGIN:VEVENT", "UID:e2", "DTSTART:20260903T140000Z",
        "SUMMARY:Midterm Exam", "END:VEVENT",
    )
    kinds = {item["title"]: item["kind"] for item in found}
    assert kinds["CS 101 Lecture"] == "event"
    assert kinds["Midterm Exam"] == "assignment"


def test_parenthesised_course_codes():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:p1", "DTSTART:20260902T140000Z",
        "SUMMARY:Essay Draft (ENG 105)", "END:VEVENT",
    )
    assert (found[0]["title"], found[0]["course"]) == ("Essay Draft", "ENG 105")


def test_summary_without_a_course_code_is_left_alone():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:p2", "DTSTART:20260902T140000Z",
        "SUMMARY:Office hours with Dr. Kim", "END:VEVENT",
    )
    assert found[0]["title"] == "Office hours with Dr. Kim"
    assert found[0]["course"] == ""


def test_results_are_sorted_by_due_date():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:b", "DTSTART:20260903T120000Z", "SUMMARY:Later", "END:VEVENT",
        "BEGIN:VEVENT", "UID:a", "DTSTART:20260901T120000Z", "SUMMARY:Sooner", "END:VEVENT",
    )
    assert [item["title"] for item in found] == ["Sooner", "Later"]


# --------------------------- window filtering -----------------------------

def test_events_outside_the_window_are_dropped():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:old", "DTSTART:20200101T120000Z", "SUMMARY:Ancient", "END:VEVENT",
        "BEGIN:VEVENT", "UID:far", "DTSTART:20400101T120000Z", "SUMMARY:Distant", "END:VEVENT",
        "BEGIN:VEVENT", "UID:ok", "DTSTART:20260601T120000Z", "SUMMARY:Current", "END:VEVENT",
    )
    assert [item["title"] for item in found] == ["Current"]


# ------------------------------ recurrence --------------------------------

def test_expands_weekly_recurrence_with_byday():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:rr-weekly",
        "DTSTART:20260907T170000Z",                      # a Monday
        "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6",
        "SUMMARY:CS 101 Lecture", "END:VEVENT",
    )
    assert len(found) == 6
    weekdays = {datetime.fromisoformat(i["due_at"]).weekday() for i in found}
    assert weekdays == {0, 2}                            # Mondays and Wednesdays
    assert len({i["uid"] for i in found}) == 6           # each occurrence is distinct


def test_respects_until_on_a_daily_rule():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:rr-daily", "DTSTART:20260901T090000Z",
        "RRULE:FREQ=DAILY;UNTIL=20260905T090000Z",
        "SUMMARY:Daily standup", "END:VEVENT",
    )
    assert [i["due_at"][:10] for i in found] == [
        "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"]


def test_honours_interval():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:rr-biweekly", "DTSTART:20260901T090000Z",
        "RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=3",
        "SUMMARY:Biweekly check-in", "END:VEVENT",
    )
    dates = [i["due_at"][:10] for i in found]
    assert dates == ["2026-09-01", "2026-09-15", "2026-09-29"]


def test_monthly_recurrence_clamps_short_months():
    """A 31st-of-the-month rule must not blow up in February."""
    found, _ = parse(
        "BEGIN:VEVENT", "UID:rr-monthly", "DTSTART:20260131T120000Z",
        "RRULE:FREQ=MONTHLY;COUNT=3", "SUMMARY:Monthly report", "END:VEVENT",
    )
    assert [i["due_at"][:10] for i in found] == ["2026-01-31", "2026-02-28", "2026-03-28"]


def test_unbounded_recurrence_is_capped_by_the_window():
    found, _ = parse(
        "BEGIN:VEVENT", "UID:rr-forever", "DTSTART:20260101T090000Z",
        "RRULE:FREQ=DAILY", "SUMMARY:Forever", "END:VEVENT",
    )
    assert 0 < len(found) <= lms.MAX_OCCURRENCES_PER_EVENT


def test_unsupported_recurrence_falls_back_to_one_occurrence():
    """Better one correct date than a wrong expansion."""
    found, _ = parse(
        "BEGIN:VEVENT", "UID:rr-weird", "DTSTART:20260901T090000Z",
        "RRULE:FREQ=SECONDLY;COUNT=5", "SUMMARY:Odd rule", "END:VEVENT",
    )
    assert len(found) == 1


# ----------------------- resilience to bad input --------------------------

def test_event_without_a_date_is_skipped_with_a_warning():
    found, warnings = parse(
        "BEGIN:VEVENT", "UID:no-date", "SUMMARY:Undated thing", "END:VEVENT",
        "BEGIN:VEVENT", "UID:fine", "DTSTART:20260901T120000Z", "SUMMARY:Real", "END:VEVENT",
    )
    assert [i["title"] for i in found] == ["Real"]   # the good event survives
    assert warnings and "skipped" in warnings[0]


def test_event_without_a_uid_still_gets_a_key():
    found, _ = parse(
        "BEGIN:VEVENT", "DTSTART:20260901T120000Z", "SUMMARY:No UID here", "END:VEVENT",
    )
    assert len(found) == 1 and found[0]["uid"]


def test_synthesized_uid_is_stable_across_processes():
    """Regression guard: this was derived from hash(), which Python randomizes
    per process — so a UID-less feed entry changed identity on every restart and
    lost whatever the student had ticked off on it."""
    import subprocess
    import sys

    script = (
        "import sys; sys.path.insert(0, %r); import lms; "
        "print(lms._synthetic_uid('Essay Draft', '2026-09-01T12:00:00+00:00'))"
        % str(__import__("pathlib").Path(lms.__file__).parent)
    )
    values = {
        subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                       check=True).stdout.strip()
        for _ in range(3)
    }
    assert len(values) == 1, f"UID changed between processes: {values}"
    assert values.pop() == lms._synthetic_uid("Essay Draft", "2026-09-01T12:00:00+00:00")


def test_synthesized_uids_differ_for_different_entries():
    a = lms._synthetic_uid("Essay Draft", "2026-09-01T12:00:00+00:00")
    b = lms._synthetic_uid("Essay Draft", "2026-09-02T12:00:00+00:00")
    c = lms._synthetic_uid("Lab Report", "2026-09-01T12:00:00+00:00")
    assert len({a, b, c}) == 3


def test_missing_summary_becomes_a_placeholder():
    found, _ = parse("BEGIN:VEVENT", "UID:x", "DTSTART:20260901T120000Z", "END:VEVENT")
    assert found[0]["title"] == "(untitled)"


def test_empty_calendar_reports_a_warning_not_an_error():
    found, warnings = parse()
    assert found == []
    assert warnings and "no dates" in warnings[0]


def test_completely_invalid_payload_raises_feederror():
    with pytest.raises(lms.FeedError):
        lms.parse_ics(b"this is not a calendar at all")


def test_accepts_str_as_well_as_bytes():
    found, _ = lms.parse_ics(
        ics("BEGIN:VEVENT", "UID:s1", "DTSTART:20260901T120000Z",
            "SUMMARY:From a string", "END:VEVENT").decode("utf-8"),
        window_start=WINDOW_START, window_end=WINDOW_END)
    assert found[0]["title"] == "From a string"


# ---------------------------- fetch behaviour -----------------------------

def test_fetch_rejects_a_non_calendar_response(monkeypatch):
    """Pointing at the calendar *web page* instead of the feed is a common
    mistake and needs a clear message, not a parse error."""
    class FakeResponse:
        def read(self, *_): return b"<!DOCTYPE html><html><body>Login page</body></html>"
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    monkeypatch.setattr(lms.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    with pytest.raises(lms.FeedError, match="didn't return a calendar"):
        lms.fetch_ics("https://school.edu/calendar")


def test_fetch_rejects_an_oversized_feed(monkeypatch):
    class FakeResponse:
        def read(self, size): return b"x" * size
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    monkeypatch.setattr(lms.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    with pytest.raises(lms.FeedError, match="larger than"):
        lms.fetch_ics("https://school.edu/f.ics", max_bytes=1024)


def test_fetch_translates_http_errors(monkeypatch):
    def raise_http(*_args, **_kwargs):
        raise lms.urllib.error.HTTPError("https://school.edu/f.ics", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(lms.urllib.request, "urlopen", raise_http)
    with pytest.raises(lms.FeedError, match="refused"):
        lms.fetch_ics("https://school.edu/f.ics")


def test_fetch_translates_timeouts(monkeypatch):
    def raise_timeout(*_args, **_kwargs):
        raise lms.urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(lms.urllib.request, "urlopen", raise_timeout)
    with pytest.raises(lms.FeedError, match="didn't respond"):
        lms.fetch_ics("https://school.edu/f.ics")


def test_fetch_succeeds_on_a_valid_feed(monkeypatch):
    payload = ics("BEGIN:VEVENT", "UID:ok", "DTSTART:20260901T120000Z",
                  "SUMMARY:Fine", "END:VEVENT")

    class FakeResponse:
        def read(self, *_): return payload
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    monkeypatch.setattr(lms.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    assert lms.fetch_ics("webcal://school.edu/f.ics") == payload


# ------------------------------- providers --------------------------------

def test_every_provider_has_usable_setup_guidance():
    assert "Canvas" in lms.PROVIDERS and "Blackboard" in lms.PROVIDERS
    for name, meta in lms.PROVIDERS.items():
        assert meta["help"].strip(), name
        assert meta["example"].startswith("http"), name


def test_gradescope_limitation_is_documented_not_implied():
    assert "Gradescope" in lms.GRADESCOPE_NOTE
    assert "manually" in lms.GRADESCOPE_NOTE
