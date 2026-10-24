"""Arabic search does not depend on optional marks or letter variants."""

import sqlite3

import pytest

from inklight import DocumentAgent
from inklight.store import Store, fts_query
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
    assert fts_query("المُستحق") == '"المستحق"'


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
    ["المستحق", "المُستحق", "القاهره", "القاهرة", "الى رئيس", "الامن", "2023", "٥٠٠", "الأول", "الاول"],
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
    assert version == "2"
    with Store(db_path) as store:  # opening again does not migrate twice
        assert len(store.keyword_search("المستحق", None, 5)) == 1


def test_deleting_a_document_removes_it_from_the_index(arabic_agent):
    doc = arabic_agent.library.documents()[0]
    arabic_agent.library.remove(doc.id)
    assert not arabic_agent.search("المستحق")
