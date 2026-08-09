"""API全体のスモークテスト。

FakeOrchestrator(conftest.py)により実際の音声取得・AIモデルには一切触れず、
FastAPIルーティング・DB CRUD・レスポンス形式のみを検証する。
"""
from __future__ import annotations


def test_create_and_list_meetings(client):
    resp = client.post("/api/meetings", json={"title": "定例会議"})
    assert resp.status_code == 200
    meeting = resp.json()
    assert meeting["title"] == "定例会議"
    assert meeting["status"] == "in_progress"
    assert client.fake_orchestrator.started == [meeting["id"]]

    resp = client.get("/api/meetings")
    assert resp.status_code == 200
    assert any(m["id"] == meeting["id"] for m in resp.json())


def test_stop_meeting_calls_orchestrator(client):
    meeting = client.post("/api/meetings", json={"title": "終了テスト"}).json()

    resp = client.post(f"/api/meetings/{meeting['id']}/stop")
    assert resp.status_code == 200
    assert client.fake_orchestrator.stopped == [meeting["id"]]


def test_participants_crud(client):
    meeting = client.post("/api/meetings", json={"title": "参加者テスト"}).json()
    meeting_id = meeting["id"]

    resp = client.post(f"/api/meetings/{meeting_id}/participants", json={"name": "松島"})
    assert resp.status_code == 200
    participant = resp.json()
    assert participant["name"] == "松島"

    resp = client.get(f"/api/meetings/{meeting_id}/participants")
    assert len(resp.json()) == 1

    resp = client.patch(
        f"/api/meetings/{meeting_id}/participants/{participant['id']}", json={"name": "松島(修正)"}
    )
    assert resp.json()["name"] == "松島(修正)"

    resp = client.delete(f"/api/meetings/{meeting_id}/participants/{participant['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/meetings/{meeting_id}/participants").json() == []


def test_speaker_assign_and_transcript_correction_flow(client):
    """話者割当・個別発言修正のフローを、DBへ直接挿入した発言データで検証する。"""
    import app.main as main_module
    from app.db.models import Speaker, Utterance

    meeting = client.post("/api/meetings", json={"title": "話者テスト"}).json()
    meeting_id = meeting["id"]

    db = main_module.app.state  # noqa: F841  (importの副作用チェック用)

    from app.db.session import SessionLocal

    db_session = SessionLocal()
    speaker = Speaker(meeting_id=meeting_id, label="speaker_01", display_label="speaker_01")
    db_session.add(speaker)
    db_session.commit()
    db_session.refresh(speaker)

    utterance = Utterance(
        meeting_id=meeting_id,
        speaker_id=speaker.id,
        start_ms=0,
        end_ms=2000,
        raw_text="それではA案件について確認します",
    )
    db_session.add(utterance)
    db_session.commit()
    db_session.refresh(utterance)
    speaker_id = speaker.id
    utterance_id = utterance.id
    db_session.close()

    # 話者名の一括割当(第18・19章)
    resp = client.post(
        f"/api/meetings/{meeting_id}/speakers/{speaker_id}/assign",
        json={"participant_name": "佐藤"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_label"] == "佐藤"

    resp = client.get(f"/api/meetings/{meeting_id}/transcript")
    assert resp.status_code == 200
    transcript = resp.json()
    assert transcript[0]["speaker_label"] == "佐藤"

    # 個別発言の文言修正(第21章)
    resp = client.patch(
        f"/api/meetings/{meeting_id}/utterances/{utterance_id}",
        json={"corrected_text": "それでは、A案件について確認いたします。"},
    )
    assert resp.status_code == 200
    assert resp.json()["effective_text"] == "それでは、A案件について確認いたします。"
    assert resp.json()["is_manually_corrected"] is True


def test_minutes_edit_flow(client):
    import app.main as main_module  # noqa: F401
    from app.db.models import MinutesSnapshot
    from app.db.session import SessionLocal

    meeting = client.post("/api/meetings", json={"title": "議事録テスト"}).json()
    meeting_id = meeting["id"]

    # 議事録が1件もない場合は404
    resp = client.get(f"/api/meetings/{meeting_id}/minutes/latest")
    assert resp.status_code == 404

    db_session = SessionLocal()
    snapshot = MinutesSnapshot(
        meeting_id=meeting_id,
        version=1,
        topics=[{"title": "A案件の納期"}],
        decisions=[],
        todos=[],
        pending_items=[],
        confirmations=[],
        changes_from_previous=[],
    )
    db_session.add(snapshot)
    db_session.commit()
    db_session.close()

    resp = client.get(f"/api/meetings/{meeting_id}/minutes/latest")
    assert resp.status_code == 200
    assert resp.json()["topics"][0]["title"] == "A案件の納期"

    resp = client.patch(
        f"/api/meetings/{meeting_id}/minutes/latest",
        json={"decisions": [{"text": "納期を8月27日に変更する"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["decisions"][0]["text"] == "納期を8月27日に変更する"
    assert resp.json()["is_manually_edited"] is True
