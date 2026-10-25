"""Arabic search does not depend on optional marks or letter variants."""

import sqlite3

import pytest

from inklight import DocumentAgent
from inklight.store import SCHEMA_VERSION, Store, fts_query
from inklight.textnorm import search_form

from .conftest import make_settings


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("المُستحق", "المستحق"),  # harakat
        ("الـــقاهرة", "القاهره"),  # tatweel; ta marbuta
        ("إلى الأمين العام", "الي الامين العام"),  # hamza-alef forms; alef maqsura
        ("آخر", "اخر"),
        ("القرار ٢٣٧٩ (٢٠١٧)", "القرار 2379 (2017)"),  # Arabic-Indic digits
        ("Invoice No. 5, Café", "Invoice No. 5, Café"),  # Latin text is left to the tokenizer
    ],
)
def test_search_form(text, expected):
    assert search_form(text) == expected


def test_query_is_not_split_at_vowel_marks():
    assert fts_query("المُستحق") == '"مستحق"'  # one term: no split at the mark, article removed


TEXT = (
    "رسالة مؤرخة ١٨ كانون الثاني/يناير ٢٠٢٣ موجهة إلى رئيس مجلس الأمن.\n"
    "المبلغ المُستحق هو ٥٠٠ جنيه، ويُدفع في القاهرة إلى الطرف الأوّل."
)


@pytest.fixture()
def arabic_agent(tmp_path):
    path = tmp_path / "letter.txt"
    path.write_text(TEXT, encoding="utf-8")
    with DocumentAgent(make_settings(tmp_path / "home")) as agent:
        agent.add([path])
        yield agent


@pytest.mark.parametrize(
    "query",
    [
        "المستحق",
        "المُستحق",
        "القاهره",
        "القاهرة",
        "الى رئيس",
        "الامن",
        "2023",
        "٥٠٠",
        "الأول",
        "الاول",
        "بالقاهرة",
        "والمبلغ",
        "مستحق",
    ],
)
def test_arabic_queries_find_the_document(arabic_agent, query):
    assert arabic_agent.search(query), query


def test_excerpts_keep_the_original_text(arabic_agent):
    hit = arabic_agent.search("المستحق")[0]
    assert "المُستحق" in hit.source.excerpt  # the index is normalised; what users see is not


OLD_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO meta VALUES ('schema_version', '1');
CREATE TABLE documents (
    id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL,
    size INTEGER, mtime REAL, pages INTEGER DEFAULT 0, total_pages INTEGER DEFAULT 0,
    status TEXT NOT NULL, doc_type TEXT DEFAULT 'unknown', engine TEXT DEFAULT '',
    error TEXT, mean_conf REAL, added_at TEXT
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER, block_start INTEGER, block_end INTEGER, text TEXT, bbox TEXT, conf REAL,
    flagged INTEGER DEFAULT 0
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='id', tokenize='porter unicode61');
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
INSERT INTO documents (id, path, name, sha256, status) VALUES ('d1', '/x/a.txt', 'a.txt', '0', 'ready');
INSERT INTO chunks (doc_id, page, block_start, block_end, text) VALUES ('d1', 1, 0, 0, 'المبلغ المُستحق في القاهرة');
"""


def test_a_version_1_library_is_reindexed(tmp_path):
    db_path = tmp_path / "library.db"
    db = sqlite3.connect(db_path)
    db.executescript(OLD_SCHEMA)
    db.close()
    with Store(db_path) as store:
        assert store.keyword_search("المستحق", None, 5)
        assert store.keyword_search("القاهره", None, 5)
        version = store._conn().execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    assert version == str(SCHEMA_VERSION)
    with Store(db_path) as store:  # opening again does not migrate twice
        assert len(store.keyword_search("المستحق", None, 5)) == 1


def test_deleting_a_document_removes_it_from_the_index(arabic_agent):
    doc = arabic_agent.library.documents()[0]
    arabic_agent.library.remove(doc.id)
    assert not arabic_agent.search("المستحق")


def test_a_version_2_library_is_reindexed_with_the_prefix_stem(tmp_path):
    db_path = tmp_path / "library.db"
    with Store(db_path) as store:
        db = store._conn()
        db.execute(
            "INSERT INTO documents (id, path, name, sha256, status) VALUES ('d1', '/x/a.txt', 'a.txt', '0', 'ready')"
        )
        # what version 2 stored: search_form only, without the prefix stem
        db.execute(
            "INSERT INTO chunks (doc_id, page, block_start, block_end, text, search_text) "
            "VALUES ('d1', 1, 0, 0, 'تختص محاكم الجيزة بالنزاع', 'تختص محاكم الجيزه بالنزاع')"
        )
        db.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
        assert not store.keyword_search("نزاع", None, 5)
    with Store(db_path) as store:
        assert store.keyword_search("نزاع", None, 5)
        assert store.keyword_search("النزاع", None, 5)


def test_a_version_3_library_is_reindexed_with_persian_letter_forms_folded(tmp_path):
    """OCR often writes the Persian yeh and keheh (ی ک) for Arabic ي and ك: "مدیر" must be found by "المدير"."""
    db_path = tmp_path / "library.db"
    with Store(db_path) as store:
        db = store._conn()
        db.execute(
            "INSERT INTO documents (id, path, name, sha256, status) VALUES ('d1', '/x/a.txt', 'a.txt', '0', 'ready')"
        )
        db.execute(
            "INSERT INTO chunks (doc_id, page, block_start, block_end, text, search_text) "
            "VALUES ('d1', 1, 0, 0, 'الصفة مدیر', 'صفه مدیر')"
        )
        db.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
        assert not store.keyword_search("المدير", None, 5)
    with Store(db_path) as store:
        hits = store.keyword_search("المدير", None, 5)
        assert hits
        assert store._conn().execute("SELECT text FROM chunks").fetchone()[0] == "الصفة مدیر"  # shown text unchanged


def test_persian_letter_forms_fold_only_in_the_search_form():
    assert search_form("مدیر کتاب") == search_form("مدير كتاب")
