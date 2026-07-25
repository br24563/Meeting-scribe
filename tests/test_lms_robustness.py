"""Adversarial input for the calendar parser.

A feed comes from a third party over the network, so the parser is the most
exposed code in the app. The contract these tests hold it to: for *any* input it
either returns records or raises FeedError — never an unexpected exception, and
never a hang.
"""
from datetime import datetime, timedelta, timezone

import pytest

import lms

WINDOW_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2030, 1, 1, tzinfo=timezone.utc)


def attempt(payload):
    """Parse `payload`, allowing only the documented failure mode."""
    try:
        found, warnings = lms.parse_ics(payload, window_start=WINDOW_START,
                                       window_end=WINDOW_END)
    except lms.FeedError:
        return None
    assert isinstance(found, list) and isinstance(warnings, list)
    for item in found:
        # Whatever came in, every record must be storable
        assert item["uid"] and item["title"]
        assert isinstance(item["all_day"], bool)
        assert item["kind"] in ("assignment", "event")
        datetime.fromisoformat(item["due_at"])  # parses, and is timezone-aware
        assert datetime.fromisoformat(item["due_at"]).tzinfo is not None
    return found


HOSTILE_PAYLOADS = [
    b"",
    b"   ",
    b"not a calendar",
    b"BEGIN:VCALENDAR",                                  # truncated
    b"BEGIN:VCALENDAR\r\nEND:VCALENDAR",                 # empty but valid
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VCALENDAR",  # unclosed VEVENT
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:garbage\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260101\r\nSUMMARY:\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;TZID=Not/AZone:20260101T120000\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260101T120000Z\r\nRRULE:FREQ=WEEKLY;BYDAY=XX,ZZ\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260101T120000Z\r\nRRULE:FREQ=DAILY;COUNT=notanumber\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260101T120000Z\r\nRRULE:FREQ=DAILY;INTERVAL=0\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260101T120000Z\r\nRRULE:FREQ=DAILY;INTERVAL=-5\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:99990101T120000Z\r\nSUMMARY:far future\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:00010101T120000Z\r\nSUMMARY:ancient\r\nEND:VEVENT\r\nEND:VCALENDAR",
    "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260101T120000Z\r\nSUMMARY:emoji 🎓 and ünïcodé\r\nEND:VEVENT\r\nEND:VCALENDAR".encode("utf-8"),
    b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260101T120000Z\r\nSUMMARY:x\r\nDTSTART:20260202T120000Z\r\nEND:VEVENT\r\nEND:VCALENDAR",
    b"\x00\x01\x02\xff\xfe binary garbage",
    b"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nSUMMARY:no date at all\r\nEND:VTODO\r\nEND:VCALENDAR",
]


@pytest.mark.parametrize("payload", HOSTILE_PAYLOADS,
                         ids=[str(i) for i in range(len(HOSTILE_PAYLOADS))])
def test_hostile_payloads_never_raise_unexpectedly(payload):
    attempt(payload)


def test_deeply_folded_and_very_long_summary():
    summary_lines = ["SUMMARY:start"] + [f" continuation-{n}" for n in range(400)]
    payload = "\r\n".join([
        "BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:long", "DTSTART:20260101T120000Z",
        *summary_lines, "END:VEVENT", "END:VCALENDAR",
    ]).encode()
    found = attempt(payload)
    assert found and len(found[0]["title"]) > 1000


def test_many_events_are_all_parsed():
    lines = ["BEGIN:VCALENDAR"]
    for n in range(1200):
        lines += ["BEGIN:VEVENT", f"UID:bulk-{n}", "DTSTART:20260301T120000Z",
                  f"SUMMARY:Item {n}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    found = attempt("\r\n".join(lines).encode())
    assert len(found) == 1200


def test_pathological_recurrence_is_bounded():
    """An unbounded daily rule over a decade-wide window must not run away."""
    payload = "\r\n".join([
        "BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:runaway", "DTSTART:20200101T090000Z",
        "RRULE:FREQ=DAILY", "SUMMARY:Every single day", "END:VEVENT", "END:VCALENDAR",
    ]).encode()
    found = attempt(payload)
    assert len(found) <= lms.MAX_OCCURRENCES_PER_EVENT


def test_many_recurring_events_together_stay_bounded():
    lines = ["BEGIN:VCALENDAR"]
    for n in range(40):
        lines += ["BEGIN:VEVENT", f"UID:rec-{n}", "DTSTART:20260101T090000Z",
                  "RRULE:FREQ=DAILY", f"SUMMARY:Series {n}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    found = attempt("\r\n".join(lines).encode())
    assert len(found) <= 40 * lms.MAX_OCCURRENCES_PER_EVENT


def test_occurrence_uids_stay_unique_within_a_series():
    """Duplicate keys would make occurrences overwrite each other on sync."""
    payload = "\r\n".join([
        "BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:series", "DTSTART:20260105T090000Z",
        "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=30",
        "SUMMARY:Daily seminar", "END:VEVENT", "END:VCALENDAR",
    ]).encode()
    found = attempt(payload)
    assert len(found) == len({item["uid"] for item in found})


def test_zero_and_negative_interval_do_not_hang():
    """INTERVAL=0 would step nowhere and loop forever if not clamped."""
    for rule in ("FREQ=DAILY;INTERVAL=0", "FREQ=WEEKLY;INTERVAL=-3",
                 "FREQ=MONTHLY;INTERVAL=0", "FREQ=YEARLY;INTERVAL=0"):
        payload = "\r\n".join([
            "BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:iv", "DTSTART:20260101T090000Z",
            f"RRULE:{rule}", "SUMMARY:x", "END:VEVENT", "END:VCALENDAR",
        ]).encode()
        found = attempt(payload)
        assert len(found) <= lms.MAX_OCCURRENCES_PER_EVENT


def test_monthly_recurrence_across_a_leap_year_boundary():
    payload = "\r\n".join([
        "BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:leap", "DTSTART:20240131T120000Z",
        "RRULE:FREQ=MONTHLY;COUNT=4", "SUMMARY:Month end", "END:VEVENT", "END:VCALENDAR",
    ]).encode()
    found = attempt(payload)
    assert [item["due_at"][:10] for item in found][:2] == ["2024-01-31", "2024-02-29"]


def test_yearly_recurrence_from_a_leap_day():
    """29 Feb yearly must clamp in non-leap years rather than raising."""
    payload = "\r\n".join([
        "BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:feb29", "DTSTART:20240229T120000Z",
        "RRULE:FREQ=YEARLY;COUNT=3", "SUMMARY:Leap day", "END:VEVENT", "END:VCALENDAR",
    ]).encode()
    found = attempt(payload)
    assert found[0]["due_at"][:10] == "2024-02-29"
    assert len(found) == 3


def test_date_only_until_includes_the_final_day():
    """A date-only UNTIL bounds the whole day, so the last occurrence counts."""
    payload = "\r\n".join([
        "BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:until-date", "DTSTART:20260901T090000Z",
        "RRULE:FREQ=DAILY;UNTIL=20260903", "SUMMARY:x", "END:VEVENT", "END:VCALENDAR",
    ]).encode()
    found = attempt(payload)
    assert [item["due_at"][:10] for item in found] == ["2026-09-01", "2026-09-02", "2026-09-03"]


def test_window_defaults_do_not_crash_without_explicit_bounds():
    payload = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:d\r\n"
               "DTSTART:20260101T120000Z\r\nSUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR").encode()
    found, warnings = lms.parse_ics(payload)   # no window arguments
    assert isinstance(found, list) and isinstance(warnings, list)


def test_split_course_handles_odd_titles():
    for title in ("", "   ", "[]", "[BIO 201]", "()", "Title []", "a" * 500,
                  "Title [very very long course code that exceeds the limit for sure indeed]"):
        result_title, course = lms.split_course(title)
        assert isinstance(result_title, str) and isinstance(course, str)


def test_classify_handles_missing_fields():
    assert lms.classify("VEVENT", None, None) == "event"
    assert lms.classify("VTODO", None, None) == "assignment"
    assert lms.classify("VEVENT", "", "") == "event"
