"""Second external review (on 914d321): conditions must be enforced, grouped and fully applied.

Plain-text invoices keep OCR out of the picture, so these tests isolate planning and execution.
Every test asserts the exact returned documents and the execution state, never just an intent or a substring.
"""

from __future__ import annotations

import csv
import io
import json
import random
from pathlib import Path

import pytest

from inklight import DocumentAgent
from inklight.agent import Policy
from inklight.agent.answer import WRITER_LABEL, grounded
from inklight.agent.expr import group
from inklight.agent.plan import Condition, Intent, Plan, Step
from inklight.agent.tools import TOOLS, Tool
from inklight.brains import Brain
from inklight.errors import PlanError, ToolError
from inklight.schemas import TaskState

from .conftest import make_settings

FOUR = {
    "small": ("Acme Supplies Ltd.", "USD 50.00", "2025-11-03"),
    "large": ("Acme Supplies Ltd.", "USD 6,000.00", "2026-02-10"),
    "other": ("Globex Corporation", "USD 7,000.00", "2026-03-15"),
    "highest": ("Initech LLC", "USD 12,000.00", "2026-05-20"),
}


def write_invoice(folder: Path, name: str, vendor: str, total: str | None, issued: str, number: int = 1) -> None:
    total_line = f"Total: {total}\n" if total else "Notes: amount to be confirmed\n"
    (folder / f"{name}.txt").write_text(
        f"INVOICE #INV-{number:04d}\nVendor: {vendor}\nInvoice Date: {issued}\nBill To: Northwind Traders\n"
        f"{total_line}",
        encoding="utf-8",
    )


def _agent(tmp_path: Path, invoices: dict) -> DocumentAgent:
    docs = tmp_path / "docs"
    docs.mkdir()
    for i, (name, (vendor, total, issued)) in enumerate(invoices.items(), 1):
        write_invoice(docs, name, vendor, total, issued, i)
    a = DocumentAgent(make_settings(tmp_path / "home"))
    report = a.add(docs)
    assert not report.failed, report.failed
    return a


@pytest.fixture
def agent(tmp_path):
    with _agent(tmp_path, FOUR) as a:
        yield a


MIXED = {
    **FOUR,
    "nototal": ("Acme Supplies Ltd.", None, "2026-06-01"),
    "euro": ("Umbrella GmbH", "EUR 9,000.00", "2026-04-04"),
}


@pytest.fixture
def mixed(tmp_path):
    with _agent(tmp_path, MIXED) as a:
        yield a


def ask(agent, request, **kw):
    return agent.ask(request, save=False, **kw)


def names(result):
    return sorted(Path(r.name).stem for r in result.records)


# ---------------------------------------------------------------- the three exact reproductions


def test_extract_from_vendor_enforces_vendor(agent):
    result = ask(agent, "Extract totals from Acme")
    assert names(result) == ["large", "small"]
    assert result.state == TaskState.SUCCEEDED
    assert any('vendor contains "Acme"' in line for line in result.interpretation)
    assert result.not_understood == () and result.warnings == ()
    # Output columns are what was asked for; the vendor was read only to apply the condition.
    assert all(set(r.fields) == {"total"} for r in result.records)


def test_range_or_threshold_keeps_grouping(agent):
    result = ask(agent, "Find invoices between $100 and $6,000 or above $10,000")
    assert names(result) == ["highest", "large"]
    assert result.state == TaskState.SUCCEEDED
    assert any("(total >= 100 USD and total <= 6,000 USD) or total > 10,000 USD" in i for i in result.interpretation)


def test_coordinated_vendors(agent):
    result = ask(agent, "Find invoices from Acme or Globex")
    assert names(result) == ["large", "other", "small"]
    assert result.state == TaskState.SUCCEEDED
    assert any('vendor contains "Acme" or vendor contains "Globex"' in i for i in result.interpretation)


# ---------------------------------------------------------------- grouping and combinations


@pytest.mark.parametrize(
    "request_,expected",
    [
        ("Extract totals from Acme above $1,000", ["large"]),
        ("Find invoices from Acme or Globex above $6,500", ["other"]),
        ("invoices from Acme, Globex and Initech above $6,500", ["highest", "other"]),
        ("invoices not from Acme or Globex", ["highest"]),
        ("invoices except Acme above $5,000", ["highest", "other"]),
        ("invoices in 2025 or above $10,000", ["highest", "small"]),
        ("invoices from February 2026 or from May 2026", ["highest", "large"]),
        ("invoices between $50 and $6,000", ["large", "small"]),  # inclusive boundaries
        ("invoices with a total of at least $6,000", ["highest", "large", "other"]),
        ("invoices with a total of at most $50", ["small"]),
        ("invoices from Acme between $1,000 and $10,000", ["large"]),
        ("Find invoices under $100 or over $10,000", ["highest", "small"]),
        # Possessives (third review): case, straight and curly apostrophes, the s' form, name first.
        ("Show acme's invoices", ["large", "small"]),
        ("Show Acme's invoices", ["large", "small"]),
        ("show ACME'S INVOICES", ["large", "small"]),
        ("Show acme’s invoices", ["large", "small"]),
        ("Acme's invoices above $1,000", ["large"]),
        ("acme’s invoices", ["large", "small"]),
        ("List Globex's bills", ["other"]),
        ("show Initech’s and Globex's invoices above $7,500", ["highest"]),
    ],
)
def test_combinations(agent, request_, expected):
    result = ask(agent, request_)
    assert names(result) == expected, (request_, result.interpretation)
    assert result.state == TaskState.SUCCEEDED, (request_, result.warnings)
    assert result.not_understood == ()


def test_empty_match_is_a_success_with_no_records(agent):
    result = ask(agent, "Find invoices above $50,000")
    assert names(result) == [] and result.state == TaskState.SUCCEEDED
    assert "No documents match total > 50,000 USD" in result.answer


def test_conditional_count_and_filtered_sum(agent):
    count = ask(agent, "how many invoices are above $5,000?")
    assert names(count) == ["highest", "large", "other"] and "3 of 4 document(s) match" in count.answer
    total = ask(agent, "What is the sum of totals from Acme?")
    assert total.intent == "aggregate" and "6,050.00 USD" in total.answer
    assert names(total) == ["large", "small"]


def test_conditions_scope_summaries_and_comparisons(agent):
    summary = ask(agent, "Summarize invoices from Globex")
    assert "other.txt" in summary.answer
    assert not any(n in summary.answer for n in ("small.txt", "large.txt", "highest.txt"))
    comparison = ask(agent, "Compare invoices from Acme")
    assert "small.txt" in comparison.answer and "large.txt" in comparison.answer
    assert "other.txt" not in comparison.answer and "highest.txt" not in comparison.answer


# ---------------------------------------------------------------- missing values and currencies


def test_missing_value_is_excluded_under_and_but_or_can_still_match(mixed):
    under_and = ask(mixed, "Find invoices from Acme above $1,000")
    assert names(under_and) == ["large"]
    assert any("nototal" in w and "no readable" in w for w in under_and.warnings)
    assert under_and.state == TaskState.PARTIAL  # a document could not be evaluated
    under_or = ask(mixed, "Find invoices from Acme or above $10,000")
    assert names(under_or) == ["highest", "large", "nototal", "small"]


def test_incompatible_currency_is_never_compared(mixed):
    result = ask(mixed, "Find invoices above $5,000")
    assert names(result) == ["highest", "large", "other"]
    assert any("euro" in w and "currency" in w for w in result.warnings)
    assert result.state == TaskState.PARTIAL
    either = ask(mixed, "Find invoices from Umbrella or above $5,000")
    assert "euro" in names(either)  # the vendor operand is true, so OR is true without comparing EUR to USD
    total = ask(mixed, "What is the sum of all invoice totals?")
    assert total.state == TaskState.PARTIAL and "By currency" in total.answer


# ---------------------------------------------------------------- exports


def _policy(tmp_path):
    return Policy(allow_write=True, output_dir=tmp_path / "out")


def test_exported_csv_rows_are_the_filtered_records(agent, tmp_path):
    result = ask(agent, "Export totals from Acme as csv", policy=_policy(tmp_path))
    assert result.state == TaskState.SUCCEEDED and len(result.files_written) == 1
    rows = list(csv.DictReader(io.StringIO(Path(result.files_written[0]).read_text(encoding="utf-8"))))
    assert sorted(Path(r["document"]).stem for r in rows) == ["large", "small"]
    assert "vendor" not in rows[0]  # internal filtering field, not a requested column
    assert sorted(float(r["total"]) for r in rows) == [50.0, 6000.0]


def test_exported_json_rows_are_the_filtered_records(agent, tmp_path):
    result = ask(agent, "Find invoices from Acme or Globex and export them as json", policy=_policy(tmp_path))
    data = json.loads(Path(result.files_written[0]).read_text(encoding="utf-8"))
    assert sorted(Path(r["document"]).stem for r in data["rows"]) == ["large", "other", "small"]
    assert any("or" in line for line in data["understood_as"])


def test_partial_selection_is_never_exported(agent, tmp_path):
    result = ask(agent, "Export invoices from Acme that were paid late as csv", policy=_policy(tmp_path))
    assert result.files_written == ()
    assert result.state == TaskState.PARTIAL
    assert any("Not saved" in w for w in result.warnings)
    assert result.answer.startswith("PARTIAL RESULT")


# ---------------------------------------------------------------- unsupported and ambiguous


def test_ambiguous_and_or_is_not_guessed(agent):
    result = ask(agent, "invoices from Acme or above $10,000 in 2026")
    assert result.state == TaskState.UNSUPPORTED
    assert result.records == ()
    assert "Nothing was run" in result.answer
    assert [s.tool for s in result.trace] == ["inspect_documents"]


def test_dangling_alternative_is_reported(agent):
    result = ask(agent, "Find invoices from Acme above $5,000 or Globex")
    assert result.state == TaskState.PARTIAL
    assert "or Globex" in result.not_understood
    assert result.answer.startswith("PARTIAL RESULT")
    assert names(result) == ["large"]  # a labelled preview of the applied part only


@pytest.mark.parametrize(
    "request_",
    [
        "Find invoices that were paid late",
        "invoices from last month",
        "top 3 invoices by total",
        "invoices in March",
        "Find invoices from March",
        "invoices before May",
    ],
)
def test_known_unsupported_phrases_stay_reported(agent, request_):
    result = ask(agent, request_)
    assert result.state != TaskState.SUCCEEDED and result.not_understood


# ---------------------------------------------------------------- plan validation


def _where():
    return group("all", [Condition(field="vendor", op="contains", value="Acme")])


def _ids(agent):
    return [d.id for d in agent.library.documents()]


def test_plan_claiming_conditions_without_a_filter_is_refused(agent):
    plan = Plan(
        intent=Intent.EXTRACT,
        query="x",
        fields=("total",),
        where=_where(),
        steps=(Step(tool="inspect_documents"), Step(tool="extract_fields", args={"fields": ["total", "vendor"]})),
    )
    with pytest.raises(PlanError, match="filter exactly once"):
        agent.run_plan(plan, _ids(agent))


def test_plan_filtering_with_a_different_expression_is_refused(agent):
    other = Condition(field="vendor", op="contains", value="Globex")
    plan = Plan(
        intent=Intent.FILTER,
        query="x",
        where=_where(),
        steps=(
            Step(tool="extract_fields", args={"fields": ["vendor"]}),
            Step(tool="filter_records", args={"where": other.model_dump(mode="json")}),
        ),
    )
    with pytest.raises(PlanError, match="does not execute"):
        agent.run_plan(plan, _ids(agent))


def test_plan_using_records_before_the_filter_is_refused(agent):
    plan = Plan(
        intent=Intent.SUMMARIZE,
        query="x",
        where=_where(),
        steps=(
            Step(tool="extract_fields", args={"fields": ["vendor"]}),
            Step(tool="summarize", args={"focus": "x"}),
            Step(tool="filter_records", args={"where": _where().model_dump(mode="json")}),
        ),
    )
    with pytest.raises(PlanError, match="before the conditions"):
        agent.run_plan(plan, _ids(agent))


def test_failed_filter_never_returns_unfiltered_records(agent, monkeypatch):
    def broken(_ctx, _args):
        raise ToolError("filter exploded")

    original = TOOLS["filter_records"]
    monkeypatch.setitem(TOOLS, "filter_records", Tool("filter_records", "broken", original.args, broken))
    result = ask(agent, "Extract totals from Acme")
    assert result.state == TaskState.FAILED and result.records == ()


def test_remote_plan_goes_through_the_same_expression(agent):
    from types import SimpleNamespace

    from inklight.agent.planner import remote_plan, validate_plan

    payload = json.dumps(
        {
            "intent": "filter",
            "match": "any",
            "conditions": [
                {"field": "vendor", "op": "contains", "value": "Acme"},
                {"field": "total", "op": "gt", "value": 10000},
            ],
        }
    )
    plan = remote_plan("x", SimpleNamespace(remote=SimpleNamespace(chat=lambda *a, **k: payload)))
    validate_plan(plan)
    assert plan.understood()[1] == 'where vendor contains "Acme" or total > 10000'


# ---------------------------------------------------------------- text presence is not correctness


def test_grounding_is_a_surface_check_only():
    assert not grounded("Bob owes Acme $100", "Bob does not owe Acme $100.")
    assert not grounded("Acme owes Bob $100", "Bob owes Acme $100.")
    # Passing it proves little: a changed quantifier slips through, which is why the writer never
    # replaces the answer.
    assert grounded("Bob owes Acme $100 every month", "Bob owes Acme $100 once.")


class _FakeWriter:
    def __init__(self, text):
        self.text = text

    def chat(self, system, user):
        return user

    def generate(self, prompt, max_new_tokens=60, check=None):
        return self.text


@pytest.mark.parametrize(
    "generated,shown",
    [("Bob owes Acme $100.", False), ("Bob does not owe Acme $100 for consulting.", True)],
)
def test_writer_never_replaces_the_extractive_answer(tmp_path, monkeypatch, closer, generated, shown):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "memo.txt").write_text("Account note.\n\nBob does not owe Acme $100 for consulting.\n", encoding="utf-8")
    a = closer(DocumentAgent(make_settings(tmp_path / "home")))
    a.add(docs)
    monkeypatch.setattr(Brain, "writer", property(lambda self: _FakeWriter(generated)))
    result = a.ask("Does Bob owe Acme $100 for consulting?", save=False)
    assert result.answer.startswith("Bob does not owe Acme $100 for consulting.")
    assert (WRITER_LABEL in result.answer) is shown
    assert result.sources and "does not owe" in result.sources[0].excerpt
    assert any(c.startswith("provenance:") and "not that they answer" in c for c in result.checks)


# ---------------------------------------------------------------- generated cases vs an independent reference

VENDORS = ["Acme", "Globex", "Initech", "Umbrella", "Hooli"]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    rng = random.Random(20261024)
    folder = tmp_path_factory.mktemp("generated")
    docs = folder / "docs"
    docs.mkdir()
    truth = {}
    for i in range(30):
        vendor = rng.choice(VENDORS)
        total = rng.choice([50, 99, 100, 250, 999, 1000, 1001, 4999, 5000, 5001, 7500, 9999, 10000, 15000])
        year = rng.choice([2025, 2026])
        name = f"g{i:02d}"
        write_invoice(docs, name, f"{vendor} Ltd.", f"USD {total:,.2f}", f"{year}-0{rng.randint(1, 9)}-1{i % 9}", i)
        truth[name] = (vendor, total, year)
    with DocumentAgent(make_settings(folder / "home")) as agent:
        agent.add(docs)
        yield agent, truth


def _cases(seed: int, n: int):
    rng = random.Random(seed)
    amounts = [100, 1000, 5000, 10000]
    templates = [
        ("Find invoices from {v1} or {v2}", lambda p, v, t, y: v in (p["v1"], p["v2"])),
        ("invoices from {v1} above ${a:,}", lambda p, v, t, y: v == p["v1"] and t > p["a"]),
        ("invoices not from {v1} below ${a:,}", lambda p, v, t, y: v != p["v1"] and t < p["a"]),
        (
            "Find invoices between ${a:,} and ${b:,} or above ${c:,}",
            lambda p, v, t, y: p["a"] <= t <= p["b"] or t > p["c"],
        ),
        ("Extract totals from {v1} or {v2} in {y}", lambda p, v, t, y: v in (p["v1"], p["v2"]) and y == p["y"]),
        ("how many invoices are at least ${a:,}?", lambda p, v, t, y: t >= p["a"]),
        ("invoices in {y} or above ${c:,}", lambda p, v, t, y: y == p["y"] or t > p["c"]),
    ]
    for _ in range(n):
        text, ref = rng.choice(templates)
        v1, v2 = rng.sample(VENDORS, 2)
        a, b = sorted(rng.sample(amounts, 2))
        params = {"v1": v1, "v2": v2, "a": a, "b": b, "c": max(b, 9999), "y": rng.choice([2025, 2026])}
        yield text.format(**params), params, ref


@pytest.mark.parametrize("request_,params,ref", list(_cases(seed=7, n=40)))
def test_generated_requests_match_reference(generated, request_, params, ref):
    agent, truth = generated
    expected = sorted(n for n, (v, t, y) in truth.items() if ref(params, v, t, y))
    result = ask(agent, request_)
    assert names(result) == expected, (request_, result.interpretation)
    assert result.state == TaskState.SUCCEEDED


# ---------------------------------------------------- unseen paraphrases: right, or honestly not "succeeded"

PARAPHRASES = [
    ("Show me every invoice issued by Acme", ["large", "small"]),
    ("Get the invoices that came from Initech", ["highest"]),
    ("anything from Globex above $1k", ["other"]),
    ("invoices that are not from Acme", ["highest", "other"]),
    ("find invoices dated 2025", ["small"]),
    ("List Acme's invoices", ["large", "small"]),
    ("Which invoices did Globex send?", ["other"]),
    ("Acme or Globex invoices please", ["large", "other", "small"]),
    ("Pull the Initech and Globex invoices", ["highest", "other"]),
    ("invoices over 5 grand from Acme", ["large"]),
    ("What did Acme bill us above $1,000?", ["large"]),
]


@pytest.mark.parametrize("request_,expected", PARAPHRASES)
def test_paraphrases_are_correct_or_honest(agent, request_, expected):
    result = ask(agent, request_)
    if result.state == TaskState.SUCCEEDED:
        assert names(result) == expected, (request_, result.interpretation)
    else:
        assert result.not_understood or result.state == TaskState.UNSUPPORTED, (request_, result.answer)


# ---------------------------------------------------------------- questions that name their document


@pytest.mark.parametrize(
    "question",
    [
        "What is the date on the Globex invoice?",
        "What is the date on Globex's invoice?",
        "What is the date on globex’s invoice?",
    ],
)
def test_question_naming_its_document_is_answered_from_that_document(agent, question):
    plan = agent.plan(question)
    assert plan.intent == Intent.ASK and plan.where is not None
    result = ask(agent, question)
    assert result.sources and all(Path(s.name).stem == "other" for s in result.sources)


@pytest.mark.parametrize(
    ("request_", "owner"),
    [
        ("What are the payment terms on Acme's invoice?", "Acme"),
        ("Show Bank of America's invoices", "Bank of America"),
        ("List the totals on Initech's invoices", "Initech"),
    ],
)
def test_possessive_owner_stops_at_a_preposition(agent, request_, owner):
    where = agent.plan(request_).where
    assert where is not None and where.value == owner


@pytest.mark.parametrize("question", ["What is on the final invoice?", "Who issued the Q2 invoice?"])
def test_lowercase_or_code_words_before_invoice_are_not_names(agent, question):
    assert agent.plan(question).where is None


def test_set_questions_stay_record_level(agent):
    assert agent.plan("What invoices are above $5,000?").intent == Intent.FILTER
    assert names(ask(agent, "Which invoices are from Acme?")) == ["large", "small"]


# ---------------------------------------------------------------- sums are computed and exposed, not just listed


def test_total_of_a_set_is_a_sum_with_a_structured_result(agent):
    plan = agent.plan("What is the total of invoices above $5,000?")
    assert plan.intent == Intent.AGGREGATE and plan.aggregate == "sum"
    result = ask(agent, "What is the total of invoices above $5,000?")
    calc = result.calculation
    assert calc["result"] == 25000.0 and calc["unit"] == "USD" and calc["count"] == 3 and calc["missing"] == 0
    assert result.state == TaskState.SUCCEEDED


def test_total_of_one_named_invoice_is_not_a_sum(agent):
    assert agent.plan("What is the total of the Globex invoice?").intent != Intent.AGGREGATE


def test_sum_reports_documents_left_out(mixed):
    calc = ask(mixed, "What is the total of all invoices?").calculation
    assert calc["missing"] == 1 and calc["count"] == len(MIXED) - 1


GAP = {**FOUR, "nototal": ("Acme Supplies Ltd.", None, "2026-06-01")}  # one total missing, one currency


@pytest.fixture
def gap(tmp_path):
    with _agent(tmp_path, GAP) as a:
        yield a


@pytest.mark.parametrize(
    ("request_", "result_"),
    [("What is the total of all invoices?", 25050.0), ("What is the average total of all invoices?", 6262.5)],
)
def test_aggregate_that_leaves_documents_out_is_partial(gap, request_, result_):
    result = ask(gap, request_)
    assert result.state == TaskState.PARTIAL  # a sum over 4 of 5 invoices is not the sum asked for
    assert result.calculation["missing"] == 1 and result.calculation["result"] == result_
    assert any("left out" in w for w in result.warnings)
    assert "1 document(s) with no total left out" in result.answer
    assert any("only part of the job" in c for c in result.checks)


def test_aggregate_over_every_document_still_succeeds(agent):
    result = ask(agent, "What is the total of all invoices?")
    assert result.state == TaskState.SUCCEEDED and result.calculation["missing"] == 0
    assert result.calculation["result"] == 25050.0
    assert "left out" not in result.answer


def test_aggregate_whose_conditions_exclude_the_gap_succeeds(gap):
    # The invoice without a total does not match "from Globex", so nothing in scope is left out.
    result = ask(gap, "What is the total of invoices from Globex?")
    assert result.state == TaskState.SUCCEEDED and result.calculation["missing"] == 0


def test_left_out_documents_are_named_in_a_per_currency_answer(mixed):
    result = ask(mixed, "What is the total of all invoices?")
    assert result.state == TaskState.PARTIAL and "1 document(s) with no total left out" in result.answer


@pytest.mark.parametrize(
    "request_", ["Find receipts above Rp 50.000", "Find receipts above Rp 50,000", "Find receipts above 50,000 IDR"]
)
def test_rupiah_amounts_in_requests(agent, request_):
    where = agent.plan(request_).where
    assert where is not None and where.value == 50000.0 and where.unit == "IDR"
