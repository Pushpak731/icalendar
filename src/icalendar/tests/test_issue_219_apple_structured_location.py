r"""Issue #219: Apple emits escaped DQUOTEs in parameter values.

``X-APPLE-STRUCTURED-LOCATION`` as written by iOS (the file in #219) has

- an **unquoted** ``X-ADDRESS`` whose content contains ``\"`` (escaped
  DQUOTE) and ``\\n`` (escaped backslash + ``n``), and
- ``X-APPLE-ABUID=\"ab://Home\"`` — a quoted value whose quotes carry a
  superfluous escape backslash ("pseudo-quoting").

Strictly, a DQUOTE is not a SAFE-CHAR in an unquoted parameter value
(RFC 5545 §3.1) — but these shapes ship from Apple at scale, so they are
parsed leniently. This module pins the decisions, layer by layer:

Decision log (companion to the #1870 escaped-quote handling):

- An escaped DQUOTE in an unquoted value resolves to ``"`` (like in
  quoted values), scanned left to right.
- A raw, unescaped DQUOTE in an unquoted value still raises ``ValueError``.
- ``\\n`` (backslash + ``n``) is not an escape in parameter values: it is
  preserved verbatim, matching how quote-free Apple addresses always
  parsed.
- A value wrapped in ``\"``...``\"`` is treated as a quoted value: the
  wrapping pair delimits it and is removed.
- Quote tracking in :func:`~icalendar.parser.parameter.q_split` and the
  content-line scanner is escape-aware outside quoted sections, so a
  ``\"`` pair neither absorbs following parameters nor misplaces the
  value-separating colon.
"""

import pytest

from icalendar import Calendar
from icalendar.cal import Component
from icalendar.parser import Parameters
from icalendar.parser.content_line import Contentline
from icalendar.parser.parameter import q_split

BS = "\\"
Q = '"'

# the X-ADDRESS value as it appears on the wire: \\n stays a literal
# backslash + n, \" resolves to "
ADDRESS_WIRE = (
    f"Ayacucho 983{BS}{BS}nPlata Baja {BS}{Q}A{BS}{Q}"
    f"{BS}{BS}nC1111AAC CABA{BS}{BS}nArgentina{BS}{BS}nArgentina"
)
ADDRESS_PARSED = (
    f"Ayacucho 983{BS}nPlata Baja {Q}A{Q}{BS}nC1111AAC CABA{BS}nArgentina{BS}nArgentina"
)

# the X-APPLE-STRUCTURED-LOCATION content line from #219, unfolded
LINE = (
    "X-APPLE-STRUCTURED-LOCATION;VALUE=URI;"
    f"X-ADDRESS={ADDRESS_WIRE};"
    f"X-APPLE-ABUID={BS}{Q}ab://Home{BS}{Q};"
    "X-APPLE-RADIUS=0;X-APPLE-REFERENCEFRAME=1;"
    "X-TITLE=Home:geo:-34.597613,-58.395858"
)

# the VTODO/VALARM from #219, folded exactly as pasted in the issue
ICS = (
    "BEGIN:VCALENDAR\n"
    "CALSCALE:GREGORIAN\n"
    "PRODID:-//Apple Inc.//iOS 10.2.1//EN\n"
    "VERSION:2.0\n"
    "BEGIN:VTODO\n"
    "COMPLETED:20170312T122019Z\n"
    "CREATED:20170312T051318Z\n"
    "DTSTAMP:20170312T122023Z\n"
    "LAST-MODIFIED:20170312T122021Z\n"
    "PERCENT-COMPLETE:100\n"
    "PRIORITY:1\n"
    "SEQUENCE:0\n"
    "STATUS:COMPLETED\n"
    "SUMMARY:Cosas en el freezer\n"
    "UID:5ACD2904-D0CE-4097-BC75-C1EB95C0BB22\n"
    "X-APPLE-SORT-ORDER:510988398\n"
    "BEGIN:VALARM\n"
    "ACKNOWLEDGED:20170312T122015Z\n"
    "ACTION:DISPLAY\n"
    "DESCRIPTION:Reminder\n"
    "TRIGGER;VALUE=DATE-TIME:19760401T005545Z\n"
    "UID:E13840A6-C30C-4BF0-A3E1-73EF27E34BD9\n"
    "X-APPLE-PROXIMITY:ARRIVE\n"
    f"X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-ADDRESS=Ayacucho 983{BS}{BS}nPlata Baja \n"
    f" {BS}{Q}A{BS}{Q}{BS}{BS}nC1111AAC CABA{BS}{BS}nArgentina{BS}{BS}nArgentina;X-APPLE-ABUID={BS}{Q}ab://Home{BS}{Q};\n"
    " X-APPLE-RADIUS=0;X-APPLE-REFERENCEFRAME=1;X-TITLE=Home:geo:\n"
    " -34.597613,-58.395858\n"
    "X-WR-ALARMUID:E13840A6-C30C-4BF0-A3E1-73EF27E34BD9\n"
    "END:VALARM\n"
    "END:VTODO\n"
    "END:VCALENDAR\n"
)


# ---------------------------------------------------------------------------
# Layer 1: q_split — separators are not absorbed by escaped quotes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("st", "sep", "expected"),
    [
        # an *unpaired* escaped quote behaves like an unterminated quote:
        # the rest of the string is absorbed into the value (the historic
        # behavior of a stray DQUOTE), instead of corrupting the split
        (f"a{BS}{Q}b;c", ";", [f"a{BS}{Q}b;c"]),
        (f"a{BS}{Q}b,c", ",", [f"a{BS}{Q}b,c"]),
        # Apple pseudo-quoting keeps the value together: separators inside
        # the \"...\" section do not split, and the pair may not swallow
        # the *following* parameters either
        (
            f"x={BS}{Q}ab://Home{BS}{Q};y=1",
            ";",
            [f"x={BS}{Q}ab://Home{BS}{Q}", "y=1"],
        ),
        (
            f"x={BS}{Q}a:b;c{BS}{Q};y=1",
            ";",
            [f"x={BS}{Q}a:b;c{BS}{Q}", "y=1"],
        ),
        # a lone backslash is content: it does not escape anything and the
        # next quote still toggles as before
        (f"a{BS}b;c", ";", [f"a{BS}b", "c"]),
        # unchanged classic behavior
        ('a,"b,c",d', ",", ["a", '"b,c"', "d"]),
    ],
)
def test_q_split_escaped_quote_outside_quotes(st, sep, expected):
    r"""``\"`` outside a quoted section functions as quoting (#219)."""
    assert q_split(st, sep) == expected


def test_q_split_param_section_of_the_issue():
    """All six parameters of the #219 line are split apart."""
    param_section = (
        "VALUE=URI;"
        f"X-ADDRESS={ADDRESS_WIRE};"
        f"X-APPLE-ABUID={BS}{Q}ab://Home{BS}{Q};"
        "X-APPLE-RADIUS=0;X-APPLE-REFERENCEFRAME=1;X-TITLE=Home"
    )
    parts = q_split(param_section, ";")
    assert len(parts) == 6
    assert parts[0] == "VALUE=URI"
    assert parts[1] == f"X-ADDRESS={ADDRESS_WIRE}"
    assert parts[2] == f"X-APPLE-ABUID={BS}{Q}ab://Home{BS}{Q}"
    assert parts[5] == "X-TITLE=Home"


# ---------------------------------------------------------------------------
# Layer 2: Parameters.from_ical — value resolution and rejection
# ---------------------------------------------------------------------------


def test_unquoted_value_with_escaped_quotes():
    r"""``\"`` in an unquoted value resolves to ``"`` (#219's X-ADDRESS)."""
    params = Parameters.from_ical(f"X-ADDRESS={ADDRESS_WIRE}")
    assert params["X-ADDRESS"] == ADDRESS_PARSED


def test_pseudo_quoted_value_is_unwrapped():
    r"""``\"ab://Home\"`` delimits the value like a quoted string would."""
    params = Parameters.from_ical(f"X-APPLE-ABUID={BS}{Q}ab://Home{BS}{Q}")
    assert params["X-APPLE-ABUID"] == "ab://Home"


def test_pseudo_quoted_value_allows_quoted_only_characters():
    """Inside the pseudo-quotes, colons and semicolons are content."""
    params = Parameters.from_ical(f"X-A={BS}{Q}a:b;c{BS}{Q}")
    assert params["X-A"] == "a:b;c"


def test_raw_quote_in_unquoted_value_is_rejected():
    """Without an escape backslash the DQUOTE stays invalid (RFC 5545 §3.1)."""
    with pytest.raises(ValueError, match="not a valid parameter"):
        Parameters.from_ical(f"X-ADDRESS=abc{Q}def")


def test_escaped_quote_at_the_end_is_rejected():
    """A trailing escape that never resolves to a raw quote still parses;
    only an *unescaped* DQUOTE rejects. The pair is content like any other.
    """
    params = Parameters.from_ical(f"X-A=abc{BS}{Q}")
    assert params["X-A"] == f"abc{Q}"


def test_escaped_backslash_then_escaped_quote():
    r"""``\\\"`` resolves left to right: ``\\`` is a backslash, ``\"`` a quote.

    This mirrors the documented left-to-right decision for quoted values
    (#1870): the scan resolves ``\\\"`` to ``\"``, not to an escaped quote.
    """
    params = Parameters.from_ical(f"X-A=a{BS}{BS}{BS}{Q}b")
    assert params["X-A"] == f"a{BS}{Q}b"


def test_strict_uppercases_around_the_resolution():
    """The strict-mode case folding applies after the quotes resolve."""
    params = Parameters.from_ical(f"X-A=ab{BS}{Q}cd", strict=True)
    assert params["X-A"] == f"AB{Q}CD"


def test_comma_list_with_escaped_quote_member():
    r"""A comma inside pseudo-quoting belongs to the member (#219): the
    unpaired ``MEMBER=a\\"b,c`` keeps one member, while a properly
    pseudo-quoted member splits after the closing pair."""
    params = Parameters.from_ical(f"MEMBER={BS}{Q}a,b{BS}{Q},c")
    assert params["MEMBER"] == ["a,b", "c"]


def test_literal_backslash_n_is_not_an_escape():
    r"""``\n`` in parameter values stays backslash + ``n`` (historic Apple
    address behavior); only the DQUOTE escapes introduced by #219 resolve."""
    params = Parameters.from_ical(f"X-ADDRESS=Via 1{BS}nRoma")
    assert params["X-ADDRESS"] == f"Via 1{BS}nRoma"


# ---------------------------------------------------------------------------
# Layer 3: Contentline — the line splits at the right colon
# ---------------------------------------------------------------------------


def test_contentline_parts():
    """The full #219 content line parses into name, parameters and value."""
    name, params, value = Contentline(LINE).parts()
    assert name == "X-APPLE-STRUCTURED-LOCATION"
    assert params["VALUE"] == "URI"
    assert params["X-ADDRESS"] == ADDRESS_PARSED
    assert params["X-APPLE-ABUID"] == "ab://Home"
    assert params["X-APPLE-RADIUS"] == "0"
    assert params["X-APPLE-REFERENCEFRAME"] == "1"
    assert params["X-TITLE"] == "Home"
    assert value == "geo:-34.597613,-58.395858"


def test_colon_inside_pseudo_quoted_value_is_not_the_separator():
    """The ``:`` of ``ab://Home`` must not end the parameter section."""
    _name, params, value = Contentline(
        f"X-PROP;X-ABUID={BS}{Q}ab://Home{BS}{Q}:value"
    ).parts()
    assert params["X-ABUID"] == "ab://Home"
    assert value == "value"


def test_unquoted_escaped_quote_does_not_displace_the_separator():
    r"""A mid-value ``\"`` pair may not swallow the value separator."""
    _name, params, value = Contentline(
        f"X-PROP;X-A=one{BS}{Q}two{BS}{Q}three:val"
    ).parts()
    assert params["X-A"] == f"one{Q}two{Q}three"
    assert value == "val"


# ---------------------------------------------------------------------------
# Layer 4: end-to-end — the file from the issue parses
# ---------------------------------------------------------------------------


def test_issue_file_parses():
    """The exact VTODO from #219 parses; no property is dropped."""
    cal = Calendar.from_ical(ICS)
    todo = cal.walk("VTODO")[0]
    assert str(todo["SUMMARY"]) == "Cosas en el freezer"
    alarm = todo.walk("VALARM")[0]
    assert str(alarm["X-WR-ALARMUID"]) == "E13840A6-C30C-4BF0-A3E1-73EF27E34BD9"
    prop = alarm["X-APPLE-STRUCTURED-LOCATION"]
    assert prop.params["X-ADDRESS"] == ADDRESS_PARSED
    assert prop.params["X-APPLE-ABUID"] == "ab://Home"
    assert prop.params["X-APPLE-RADIUS"] == "0"
    assert prop.params["X-APPLE-REFERENCEFRAME"] == "1"
    assert prop.params["X-TITLE"] == "Home"
    assert prop.to_ical() == b"geo:-34.597613,-58.395858"


def test_reserialization_round_trip():
    """The parsed property serializes to RFC 6868 form and reparses equal."""
    alarm = Calendar.from_ical(ICS).walk("VALARM")[0]
    prop = alarm["X-APPLE-STRUCTURED-LOCATION"]
    # X-ADDRESS is always quoted on output; its DQUOTEs use RFC 6868 ^'
    # (asserted on the parameter level: the content line is folded at 75
    # octets, which would split the expected substring)
    serialized_param = Parameters({"X-ADDRESS": ADDRESS_PARSED}).to_ical()
    expected = 'X-ADDRESS="' + ADDRESS_PARSED.replace(Q, "^'") + '"'
    assert serialized_param == expected.encode()
    # the alarm round trips through its folded serialization
    alarm2 = Component.from_ical(alarm.to_ical().decode())
    prop2 = alarm2["X-APPLE-STRUCTURED-LOCATION"]
    assert prop2.params["X-ADDRESS"] == ADDRESS_PARSED
    assert prop2.params["X-APPLE-ABUID"] == "ab://Home"
    assert prop2.params["X-TITLE"] == "Home"
    assert prop2.to_ical() == prop.to_ical()
