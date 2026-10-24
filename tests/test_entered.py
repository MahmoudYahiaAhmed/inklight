"""Strict parsing of amounts a reviewer types: never delete characters to make an input fit."""

from decimal import Decimal

import pytest

from inklight import DocumentAgent
from inklight.entered import parse_entered_amount, parse_entered_date
from inklight.errors import InputRejected

from .conftest import make_settings


@pytest.mark.parametrize(
    ("text", "value", "currency"),
    [
        ("1234", "1234", None),
        ("12.50", "12.50", None),
        ("12,5", "12.5", None),
        ("1,234.56", "1234.56", None),  # US / UK
        ("1.234,56", "1234.56", None),  # most of Europe
        ("1 234,56", "1234.56", None),  # French, with a space
        ("1 234,56", "1234.56", None),  # no-break space
        ("1'234.50", "1234.50", None),  # Swiss
        ("63.000", "63000", None),  # IDR: three digits after one dot group thousands
        ("Rp 63.000", "63000", "Rp"),
        ("USD 1,000", "1000", "USD"),
        ("1,000 $", "1000", "$"),
        ("(45.00)", "-45.00", None),  # accounting negative
        ("-45.00", "-45.00", None),
        ("−45", "-45", None),  # Unicode minus
        ("١٢٣٫٤٥", "123.45", None),  # Arabic-Indic digits, Arabic decimal sign
        ("١٬٢٣٤", "1234", None),  # Arabic thousands separator
        ("1.234.567,89", "1234567.89", None),
    ],
)
def test_supported_formats(text, value, currency):
    assert parse_entered_amount(text) == (Decimal(value), currency)


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("100 + 20", "not a plain amount"),  # was stored as 10020
        ("1e3", "not a plain amount"),  # was stored as 13
        ("12abc 34", "not a plain amount"),  # was stored as 1234
        ("1,2,3", "irregular digit groups"),  # was stored as 12.3
        ("100 20", "irregular digit groups"),
        ("1,23,456", "irregular digit groups"),  # lakh grouping is not supported
        ("--5", "not a plain amount"),
        ("-(45)", "not a plain amount"),
        ("$1,000 USD", "more than one currency"),
        ("12.345,678", "at most 2"),
        (".5", "not a plain amount"),
        ("5.", "not a plain amount"),
        ("", "Enter a value"),
    ],
)
def test_unsupported_expressions_and_notation_are_rejected(text, why):
    with pytest.raises(InputRejected, match=why):
        parse_entered_amount(text)


def test_number_fields_allow_more_decimals_than_money():
    assert parse_entered_amount("2,125", money=False) == (Decimal("2125"), None)  # still thousands
    assert parse_entered_amount("1.5", money=False)[0] == Decimal("1.5")


def test_the_reviewers_input_is_kept_next_to_the_parsed_value(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("INVOICE #1\nVendor: Acme Ltd\nTotal: USD 10.00\n", encoding="utf-8")
    with DocumentAgent(make_settings(tmp_path / "home")) as agent:
        agent.add(docs)
        r = agent.open_review(agent.library.documents()[0].id, ["total"], reviewer="ana")
        with pytest.raises(InputRejected):
            agent.reviews.decide(r.id, "total", reviewer="ana", action="corrected", value="100 + 20")
        assert agent.reviews.get(r.id).fields[0].action is None  # nothing stored for a rejected input
        r = agent.reviews.decide(r.id, "total", reviewer="ana", action="corrected", value="(1.234,50)")
        f = r.fields[0]
        assert f.final == -1234.5 and f.entered == "(1.234,50)" and f.predicted == 10.0
        events = agent.reviews.events(r.id)
        assert events[-1]["after"] == {"final": -1234.5, "entered": "(1.234,50)", "action": "corrected"}
        agent.reviews.approve(r.id, reviewer="ana")
        row = agent.reviews.export("json", actor="ana")
        assert '"entered_input": "(1.234,50)"' in row


def test_an_older_review_table_gains_the_input_column(tmp_path):
    import sqlite3

    from inklight.review import ReviewStore
    from inklight.store import Store

    db_path = tmp_path / "library.db"
    db = sqlite3.connect(db_path)
    db.executescript(
        "CREATE TABLE review_fields (review_id TEXT NOT NULL, field TEXT NOT NULL, position INTEGER NOT NULL, "
        "predicted TEXT, raw TEXT, confidence REAL, method TEXT, warning TEXT, source TEXT, flagged INTEGER NOT NULL, "
        "final TEXT, action TEXT, updated_by TEXT, updated_at TEXT, PRIMARY KEY (review_id, field));"
    )
    db.close()
    with Store(db_path) as store:
        ReviewStore(store)
        columns = {row[1] for row in store._conn().execute("PRAGMA table_info(review_fields)")}
    assert "entered" in columns


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("JAN04/00", "2000-01-04"),  # as the Bozell invoice in the rehearsal writes it
        ("JAN24/00", "2000-01-24"),
        ("FEB12/03", "2003-02-12"),
        ("jan04/00", "2000-01-04"),
        ("JAN 04/00", "2000-01-04"),
        ("Jan-04-2000", "2000-01-04"),
        ("Jan. 4, 2000", "2000-01-04"),
        ("January 4 2000", "2000-01-04"),
        ("Sept 30, 82", "1982-09-30"),
        ("04-JAN-00", "2000-01-04"),
        ("04JAN00", "2000-01-04"),
        ("4 January 2000", "2000-01-04"),
        ("4th Jan 2000", "2000-01-04"),
        ("01/31/82", "1982-01-31"),  # numeric forms keep working
        ("12-03-91", "1991-12-03"),
        ("4/1/91", "1991-04-01"),
        ("2026-01-31", "2026-01-31"),
        ("  2000-01-04 ", "2000-01-04"),
        ("٠١/٣١/١٩٨٢", "1982-01-31"),  # Arabic-Indic digits
    ],
)
def test_entered_dates(text, iso):
    assert parse_entered_date(text).isoformat() == iso


@pytest.mark.parametrize(
    "text",
    [
        "JAN32/00",  # no such day
        "FEB30/03",
        "13/13/2020",
        "JAN04",  # no year
        "JAN/00",
        "JAN04/000",
        "JANX4/00",
        "Janu 4 2000",  # not a month name
        "JAN04/00 approx",  # extra words are not dropped
        "about 01/31/82",
        "01/31/82 or 02/01/82",  # two dates
        "soon",
        "",
    ],
)
def test_entered_dates_are_strict(text):
    with pytest.raises(InputRejected):
        parse_entered_date(text)
