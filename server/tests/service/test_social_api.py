"""Friends and sharing through the API (R2-7, ADR 0007).

Covers: invite codes (single use, hashed, expiring, revocable, forgiving to
type), friendship, sharing (friends only, validated subjects, moderated notes,
send limits), the inbox and read state, blocking (silent, mutual), reports,
export, account deletion, and that a user can only ever reach their own data.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from songnexus.catalog.ingest import ingest_snapshot
from songnexus.catalog.snapshot import write_snapshot
from songnexus.config import Settings
from songnexus.core import ids
from songnexus.jobs.purge import run_purge
from songnexus.service.app import build_state
from songnexus.service.deps import AppState
from songnexus.service.routes import social as social_routes
from songnexus.social import invites
from songnexus.storage import migrate
from songnexus.storage import models as m
from songnexus.storage.db import make_engine, session_scope
from tests.catalog import fixtures as fx
from tests.service.test_identity import FakeVerifier, new_client, reason, sign_in

ALICE = ids.artist_id("mb-alice")
BOB = ids.artist_id("mb-bob")
SONG = ids.recording_id(f"song|{ALICE}")


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    snapshot = tmp_path / "snapshot.jsonl.gz"
    write_snapshot(fx.small_catalog(), snapshot)
    url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = make_engine(url)
    migrate.upgrade(engine)
    ingest_snapshot(engine, snapshot)
    built = build_state(Settings(database_url=url, log_json=False, read_model_refresh_s=3600))
    built.verifier = FakeVerifier()
    return built


def _person(state: AppState, uid: str, name: str | None) -> TestClient:
    client = new_client(state)
    client.__enter__()
    sign_in(client, uid)
    if name is not None:
        response = client.patch("/v1/users/me/socialProfile", json={"displayName": name})
        assert response.status_code == 200, response.text
    return client


@pytest.fixture
def people(state: AppState) -> Iterator[dict[str, TestClient]]:
    clients = {
        "ana": _person(state, "uid-ana", "Ana"),
        "ben": _person(state, "uid-ben", "Ben"),
        "cy": _person(state, "uid-cy", "Cy"),
    }
    yield clients
    for c in clients.values():
        c.__exit__(None, None, None)


def _me(client: TestClient) -> str:
    return str(client.get("/v1/sessions/current").json()["user"])


def _invite(client: TestClient) -> str:
    response = client.post("/v1/users/me/friendInvites")
    assert response.status_code == 200, response.text
    return str(response.json()["code"])


def _befriend(a: TestClient, b: TestClient) -> None:
    code = _invite(a)
    response = b.post(f"/v1/friendInvites/{code}:accept")
    assert response.status_code == 200, response.text


def _share(sender: TestClient, recipient: TestClient, **body: Any) -> Any:
    payload = {"recipient": _me(recipient), "kind": "ARTIST", "subjects": [f"artists/{ALICE}"]}
    payload.update(body)
    return sender.post("/v1/shares", json=payload)


# ---------------------------------------------------------------------------
# Invite codes
# ---------------------------------------------------------------------------


def test_codes_are_forgiving_to_type() -> None:
    code = invites.new_code()
    assert invites.normalize(invites.display(code).lower()) == code
    assert invites.normalize(" abcde - fghjk ") == "ABCDEFGHJK"
    assert invites.normalize("0O1IL00000") == "0011100000"
    assert invites.normalize("short") is None
    assert invites.normalize("ABCDE-FGHJU") is None  # U is not in the alphabet


def test_an_invite_makes_two_people_friends_and_is_single_use(
    people: dict[str, TestClient], state: AppState
) -> None:
    ana, ben, cy = people["ana"], people["ben"], people["cy"]
    created = ana.post("/v1/users/me/friendInvites").json()
    code = created["code"]
    assert len(code) == 11
    assert code[5] == "-"
    # Only the hash is stored, and the list never shows the code again.
    with session_scope(state.engine) as session:
        stored = session.scalars(select(m.FriendInvite)).one()
        assert stored.code_hash == invites.code_hash(invites.normalize(code) or "")
        assert code.replace("-", "") not in stored.code_hash
    listed = ana.get("/v1/users/me/friendInvites").json()["friendInvites"]
    assert [i["code"] for i in listed] == [""]

    preview = ben.get(f"/v1/friendInvites/{code.lower()}")
    assert preview.status_code == 200
    assert preview.json()["inviter"]["displayName"] == "Ana"
    assert preview.json()["alreadyFriends"] is False

    accepted = ben.post(f"/v1/friendInvites/{code}:accept")
    assert accepted.status_code == 200
    assert accepted.json()["person"]["displayName"] == "Ana"
    assert [
        f["person"]["displayName"] for f in ana.get("/v1/users/me/friends").json()["friends"]
    ] == ["Ben"]
    assert [
        f["person"]["displayName"] for f in ben.get("/v1/users/me/friends").json()["friends"]
    ] == ["Ana"]
    # Used up: nobody else can use it.
    again = cy.post(f"/v1/friendInvites/{code}:accept")
    assert again.status_code == 404
    assert reason(again) == "INVITE_NOT_VALID"
    assert ana.get("/v1/users/me/friendInvites").json()["friendInvites"] == []


def test_invites_cannot_be_used_by_their_creator_or_after_revocation(
    people: dict[str, TestClient],
) -> None:
    ana, ben = people["ana"], people["ben"]
    code = _invite(ana)
    assert reason(ana.post(f"/v1/friendInvites/{code}:accept")) == "INVITE_NOT_VALID"
    invite = ana.get("/v1/users/me/friendInvites").json()["friendInvites"][0]["name"]
    invite_id = invite.rsplit("/", 1)[1]
    assert ana.delete(f"/v1/users/me/friendInvites/{invite_id}").status_code == 200
    assert reason(ben.post(f"/v1/friendInvites/{code}:accept")) == "INVITE_NOT_VALID"
    assert reason(ben.get("/v1/friendInvites/not-a-code")) == "INVITE_NOT_VALID"


def test_invites_expire_after_seven_days(people: dict[str, TestClient], state: AppState) -> None:
    ana, ben = people["ana"], people["ben"]
    code = _invite(ana)
    with session_scope(state.engine) as session:
        row = session.scalars(select(m.FriendInvite)).one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert reason(ben.post(f"/v1/friendInvites/{code}:accept")) == "INVITE_NOT_VALID"
    assert run_purge(state.engine)["expiredInvites"] == 1


def test_open_invites_are_capped(people: dict[str, TestClient]) -> None:
    ana = people["ana"]
    for _ in range(social_routes.MAX_ACTIVE_INVITES):
        _invite(ana)
    response = ana.post("/v1/users/me/friendInvites")
    assert response.status_code == 400
    assert reason(response) == "TOO_MANY_INVITES"


def test_a_display_name_is_needed_to_invite_or_accept(
    state: AppState, people: dict[str, TestClient]
) -> None:
    nameless = _person(state, "uid-dee", None)
    try:
        assert reason(nameless.post("/v1/users/me/friendInvites")) == "DISPLAY_NAME_REQUIRED"
        code = _invite(people["ana"])
        assert reason(nameless.post(f"/v1/friendInvites/{code}:accept")) == "DISPLAY_NAME_REQUIRED"
        assert nameless.get("/v1/users/me/socialProfile").json()["displayName"] == ""
    finally:
        nameless.__exit__(None, None, None)


def test_display_names_are_moderated_and_tidied(people: dict[str, TestClient]) -> None:
    ana = people["ana"]
    link = ana.patch("/v1/users/me/socialProfile", json={"displayName": "visit spam.com"})
    assert link.status_code == 400
    assert reason(link) == "TEXT_HAS_LINK"
    hidden = ana.patch(
        "/v1/users/me/socialProfile", json={"displayName": "A\N{RIGHT-TO-LEFT OVERRIDE}B"}
    )
    assert reason(hidden) == "TEXT_HAS_HIDDEN_CHARACTERS"
    tidy = ana.patch(
        "/v1/users/me/socialProfile", json={"displayName": "  Ana   María \U0001f3b6 "}
    )
    assert tidy.json()["displayName"] == "Ana María \U0001f3b6"


def test_friends_need_sign_in_and_stay_private(
    state: AppState, people: dict[str, TestClient]
) -> None:
    with new_client(state) as anonymous:
        assert anonymous.get("/v1/users/me/friends").status_code == 401
        assert anonymous.get("/v1/friendInvites/ABCDE-FGHJK").status_code == 401
    ana, ben = people["ana"], people["ben"]
    other = _me(ben).removeprefix("users/")
    assert ana.get(f"/v1/users/{other}/friends").status_code == 403
    assert ana.get(f"/v1/users/{other}/inbox").status_code == 403


def test_friends_can_be_switched_off(state: AppState, people: dict[str, TestClient]) -> None:
    state.flags["friends"] = False
    response = people["ana"].get("/v1/users/me/friends")
    assert response.status_code == 503
    assert reason(response) == "FLAG_OFF"


# ---------------------------------------------------------------------------
# Sharing and the inbox
# ---------------------------------------------------------------------------


def test_friends_share_and_the_inbox_tracks_read_state(people: dict[str, TestClient]) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    sent = _share(ana, ben, note="  You'd love the bridge on this one  ")
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["note"] == "You'd love the bridge on this one"
    assert body["subjects"] == [
        {"name": f"artists/{ALICE}", "displayName": "Alice", "available": True}
    ]
    assert body["sender"]["displayName"] == "Ana"

    song = _share(
        ana, ben, kind="RECORDING_COMPARISON", subjects=[f"recordings/{SONG}", f"recordings/{SONG}"]
    )
    assert reason(song) == "INVALID_ARGUMENT"  # two different subjects
    path = _share(ana, ben, kind="PATH", subjects=[f"artists/{ALICE}", f"artists/{BOB}"])
    assert path.status_code == 200
    one_song = _share(ana, ben, kind="RECORDING", subjects=[f"recordings/{SONG}"])
    assert one_song.status_code == 200
    assert one_song.json()["subjects"][0]["available"] is True

    inbox = ben.get("/v1/users/me/inbox").json()
    assert inbox["unreadCount"] == 3
    assert [s["kind"] for s in inbox["shares"]] == ["RECORDING", "PATH", "ARTIST"]
    first = inbox["shares"][0]["name"]
    read = ben.post(f"/v1/{first}:markRead")
    assert read.status_code == 200, read.text
    assert read.json()["read"] is True
    assert ben.get("/v1/users/me/inbox").json()["unreadCount"] == 2
    assert ben.post("/v1/users/me/inbox:markRead").json()["marked"] == 2
    assert ben.get("/v1/users/me/inbox").json()["unreadCount"] == 0
    # The sender can't mark the recipient's share; nobody else can see it.
    assert ana.post(f"/v1/{first}:markRead").status_code == 404
    assert ana.get("/v1/users/me/inbox").json()["shares"] == []


def test_sharing_needs_a_friendship(people: dict[str, TestClient]) -> None:
    ana, cy = people["ana"], people["cy"]
    response = _share(ana, cy)
    assert response.status_code == 404
    assert reason(response) == "FRIEND_NOT_FOUND"


def test_shares_are_validated_against_the_catalog(people: dict[str, TestClient]) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    unknown = ids.artist_id("mb-nobody")
    assert reason(_share(ana, ben, subjects=[f"artists/{unknown}"])) == "SUBJECT_NOT_FOUND"
    assert reason(_share(ana, ben, subjects=["artists/not-an-id"])) == "INVALID_ARGUMENT"
    assert reason(_share(ana, ben, kind="ARTIST_COMPARISON")) == "INVALID_ARGUMENT"
    wrong_type = _share(ana, ben, kind="RECORDING", subjects=[f"artists/{ALICE}"])
    assert wrong_type.status_code == 400


def test_notes_are_moderated_and_limited(people: dict[str, TestClient]) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    assert reason(_share(ana, ben, note="free tickets at https://x.test")) == "TEXT_HAS_LINK"
    assert reason(_share(ana, ben, note="a" * 12)) == "TEXT_REJECTED"
    assert _share(ana, ben, note="x" * 141).status_code == 400
    assert _share(ana, ben, note="\U0001f468‍\U0001f469‍\U0001f467 for the family").status_code == 200


def test_senders_are_rate_limited(people: dict[str, TestClient], monkeypatch: Any) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    monkeypatch.setattr(social_routes, "SEND_LIMITS", ((timedelta(hours=1), 2),))
    assert _share(ana, ben).status_code == 200
    assert _share(ana, ben).status_code == 200
    limited = _share(ana, ben)
    assert limited.status_code == 429
    assert reason(limited) == "SHARE_LIMIT"


def test_recipients_and_senders_can_remove_shares(people: dict[str, TestClient]) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    first = _share(ana, ben).json()["name"]
    second = _share(ana, ben).json()["name"]
    assert ben.delete(f"/v1/{first}").status_code == 200
    assert ana.delete(f"/v1/{second}").status_code == 200  # unsend
    assert ben.get("/v1/users/me/inbox").json()["shares"] == []
    assert people["cy"].delete(f"/v1/{first}").status_code == 404


def test_inbox_leaves_out_artists_the_listener_blocked(people: dict[str, TestClient]) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    _share(ana, ben)
    assert (
        ben.post("/v1/users/me/blockedArtists", json={"artist": f"artists/{ALICE}"}).status_code
        == 200
    )
    assert ben.get("/v1/users/me/inbox").json()["shares"] == []


def test_unfriending_stops_sharing_but_keeps_what_was_sent(people: dict[str, TestClient]) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    _share(ana, ben)
    ben_id = _me(ben).removeprefix("users/")
    assert ana.delete(f"/v1/users/me/friends/{ben_id}").status_code == 200
    assert ben.get("/v1/users/me/friends").json()["friends"] == []
    assert reason(_share(ana, ben)) == "FRIEND_NOT_FOUND"
    assert len(ben.get("/v1/users/me/inbox").json()["shares"]) == 1


# ---------------------------------------------------------------------------
# Blocking and reports
# ---------------------------------------------------------------------------


def test_blocking_is_silent_and_mutual(people: dict[str, TestClient]) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    _share(ana, ben)
    _share(ben, ana)
    ana_id = _me(ana)
    blocked = ben.post("/v1/users/me/blockedUsers", json={"user": ana_id})
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["person"]["displayName"] == "Ana"
    # Both lose the friendship and the shares between them, both ways.
    assert ana.get("/v1/users/me/friends").json()["friends"] == []
    assert ana.get("/v1/users/me/inbox").json()["shares"] == []
    assert ben.get("/v1/users/me/inbox").json()["shares"] == []
    # Ana can't reach Ben again; her invite and her shares fail like any invalid one.
    assert reason(_share(ana, ben)) == "FRIEND_NOT_FOUND"
    code = _invite(ana)
    assert reason(ben.post(f"/v1/friendInvites/{code}:accept")) == "INVITE_NOT_VALID"
    code = _invite(ben)
    assert reason(ana.get(f"/v1/friendInvites/{code}")) == "INVITE_NOT_VALID"
    assert reason(ben.post("/v1/users/me/blockedUsers", json={"user": ana_id})) == "ALREADY_BLOCKED"
    # Unblocking doesn't restore the friendship.
    ana_raw = ana_id.removeprefix("users/")
    assert [
        b["person"]["user"] for b in ben.get("/v1/users/me/blockedUsers").json()["blockedUsers"]
    ] == [ana_id]
    assert ben.delete(f"/v1/users/me/blockedUsers/{ana_raw}").status_code == 200
    assert ben.get("/v1/users/me/friends").json()["friends"] == []


def test_only_people_you_know_can_be_blocked(people: dict[str, TestClient]) -> None:
    ana, cy = people["ana"], people["cy"]
    response = ana.post("/v1/users/me/blockedUsers", json={"user": _me(cy)})
    assert response.status_code == 404
    assert reason(response) == "PERSON_NOT_FOUND"


def test_reporting_a_share_keeps_a_copy_and_clears_it(
    people: dict[str, TestClient], state: AppState
) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    share = _share(ana, ben, note="rude words").json()["name"]
    report = ben.post("/v1/reports", json={"share": share, "reason": "HARASSMENT"})
    assert report.status_code == 200, report.text
    assert ben.get("/v1/users/me/inbox").json()["shares"] == []
    with session_scope(state.engine) as session:
        row = session.scalars(select(m.AbuseReport)).one()
        assert row.share_note == "rude words"
        assert row.reported_user_id == _me(ana).removeprefix("users/")
        row.created_at = datetime.now(UTC) - timedelta(days=91)
    assert run_purge(state.engine)["expiredReports"] == 1
    neither = ben.post("/v1/reports", json={"reason": "SPAM"})
    assert neither.status_code == 400
    stranger = people["cy"].post("/v1/reports", json={"user": _me(ana), "reason": "SPAM"})
    assert reason(stranger) == "PERSON_NOT_FOUND"


# ---------------------------------------------------------------------------
# Export and deletion
# ---------------------------------------------------------------------------


def test_export_covers_friends_and_sharing_without_codes(people: dict[str, TestClient]) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    _share(ana, ben, note="hi")
    open_code = _invite(ana)
    data = ana.get("/v1/users/me:export").json()
    social = data["social"]
    assert social["displayName"] == "Ana"
    assert [f["user"] for f in social["friends"]] == [_me(ben)]
    assert len(social["friendInvites"]) == 1
    assert open_code not in str(data)
    assert open_code.replace("-", "") not in str(data)
    assert [s["note"] for s in social["sharesSent"]] == ["hi"]
    assert len(ben.get("/v1/users/me:export").json()["social"]["sharesReceived"]) == 1
    actions = {e["action"] for e in data["auditLog"]}
    assert {"socialProfile.update", "friendInvite.create", "friend.add", "share.create"} <= actions


def test_deleting_an_account_removes_its_shares_from_friends_inboxes(
    people: dict[str, TestClient], state: AppState
) -> None:
    ana, ben = people["ana"], people["ben"]
    _befriend(ana, ben)
    _share(ana, ben)
    _invite(ana)
    ana_id = _me(ana).removeprefix("users/")
    assert ana.delete("/v1/users/me").status_code == 200
    assert ben.get("/v1/users/me/inbox").json()["shares"] == []
    assert ben.get("/v1/users/me/friends").json()["friends"] == []
    with session_scope(state.engine) as session:
        for model, column in (
            (m.SocialProfile, m.SocialProfile.user_id),
            (m.FriendInvite, m.FriendInvite.user_id),
            (m.Friendship, m.Friendship.friend_id),
            (m.Share, m.Share.sender_id),
        ):
            assert session.scalars(select(model).where(column == ana_id)).first() is None
