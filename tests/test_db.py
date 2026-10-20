from reelfactory import db


def test_ids_status_and_attempts(tmp_path):
    path = tmp_path / "ideas.db"
    with db.connect(path) as con:
        assert db.next_id(con, "20261019") == "AI-20261019-001"
        db.upsert_idea(con, "AI-20261019-001", "Demo", status="new")
        assert db.next_id(con, "20261019") == "AI-20261019-002"
        db.set_status(con, "AI-20261019-001", "failed", error="boom", bump_attempt=True)
    with db.connect(path) as con:
        row = db.get(con, "AI-20261019-001")
        assert row["status"] == "failed" and row["error"] == "boom" and row["attempts"] == 1
        db.upsert_idea(con, "AI-20261019-001", "Demo v2")
        assert db.get(con, "AI-20261019-001")["title"] == "Demo v2"
