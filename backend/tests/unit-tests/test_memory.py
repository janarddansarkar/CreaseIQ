import sqlite3

from memory import MemoryStore


def test_creates_schema_and_wal(store):
    names = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "turns", "user_memory"} <= names
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_user_cap_evicts_oldest_with_their_data(tmp_path):
    s = MemoryStore(tmp_path / "m.sqlite", max_users=3, max_turns=5)
    for u in ("u1", "u2", "u3"):
        s.ensure_user(u)
        s.record_turn(u, "q", "a", "answered", "ODI", None)
        s.update_profile(u, fmt="ODI")
    evicted = s.ensure_user("u4")
    assert evicted == ["u1"]
    assert s.turns("u1") == [] and s.get_profile("u1")["preferred_format"] is None
    assert s.turns("u2") != []
    assert s.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3


def test_existing_user_is_not_evicted_again(tmp_path):
    s = MemoryStore(tmp_path / "m.sqlite", max_users=2)
    s.ensure_user("a"), s.ensure_user("b")
    assert s.ensure_user("a") == [] and s.ensure_user("b") == []


def test_turn_cap_drops_oldest_turn(tmp_path):
    s = MemoryStore(tmp_path / "m.sqlite", max_turns=3)
    s.ensure_user("u")
    for i in range(6):
        s.record_turn("u", f"q{i}", f"a{i}", "answered", None, None)
    assert [t["question"] for t in s.turns("u")] == ["q3", "q4", "q5"]


def test_turns_are_per_user_and_ordered(store):
    store.record_turn("a", "q1", "a1", "answered", "ODI", "3.1", {"k": 1})
    store.record_turn("b", "qb", "ab", "answered", None, None)
    store.record_turn("a", "q2", "a2", "unsupported", None, None)
    ta = store.turns("a")
    assert [t["question"] for t in ta] == ["q1", "q2"] and ta[0]["digest"] == {"k": 1} and ta[1]["digest"] is None
    assert len(store.turns("b")) == 1


def test_profile_defaults_and_updates(store):
    assert store.get_profile("nobody") == {"preferred_format": None, "preferred_language": None, "topics": []}
    store.update_profile("u", fmt="T20I", language="en", topic="overs")
    store.update_profile("u", topic="free hit")
    p = store.get_profile("u")
    assert p == {"preferred_format": "T20I", "preferred_language": "en", "topics": ["overs", "free hit"]}      # None keeps the old value


def test_topics_dedupe_move_to_end_and_cap(tmp_path):
    s = MemoryStore(tmp_path / "m.sqlite", max_topics=3)
    for t in ("a", "b", "c", "a", "d"):
        s.update_profile("u", topic=t)
    assert s.get_profile("u")["topics"] == ["c", "a", "d"]


def test_delete_user_removes_everything(store):
    store.ensure_user("u")
    store.record_turn("u", "q", "a", "answered", None, None)
    store.update_profile("u", fmt="ODI")
    store.delete_user("u")
    assert store.turns("u") == [] and store.get_profile("u")["preferred_format"] is None
    assert store.conn.execute("SELECT COUNT(*) FROM users WHERE user_id='u'").fetchone()[0] == 0


def test_prune_checkpoints_is_a_noop_without_checkpoint_tables(store):
    store.prune_checkpoints("u")      # must not raise


def test_migrates_a_database_created_before_digests(tmp_path):
    p = tmp_path / "old.sqlite"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, ts REAL, question TEXT, answer TEXT, status TEXT, format TEXT, clause TEXT)")
    c.commit(), c.close()
    s = MemoryStore(p)
    s.record_turn("u", "q", "a", "answered", None, None, {"x": 1})
    assert s.turns("u")[0]["digest"] == {"x": 1}
