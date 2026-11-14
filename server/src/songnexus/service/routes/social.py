"""Friends and sharing (R2-7, ADR 0007).

Friends join only by invite code: no search, no contact upload, no directory.
Friends see each other's display name and what they share, nothing else.
Sharing needs a friendship; blocks are silent and hide both people from each
other; notes and names pass the moderation hook; sends are limited per user,
counted in the database so the limit holds across instances. Every change is
audited, exported and erased with the account.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from songnexus.logs import request_id_var
from songnexus.service import schemas as api
from songnexus.service.deps import (
    Viewer,
    app_state,
    authorize_user,
    check_write_origin,
    parse_name,
    rate_limited,
    read_model,
    viewer,
)
from songnexus.service.errors import ApiError, Status, invalid_argument, not_found
from songnexus.service.pagination import paginate
from songnexus.service.ratelimit import MethodClass
from songnexus.service.readmodel import ReadModel
from songnexus.service.routes.common import PageSize, PageToken, db_session
from songnexus.social import invites
from songnexus.social.moderation import Verdict
from songnexus.storage import models as m
from songnexus.storage import social_repository as social
from songnexus.storage import user_repository as users

router = APIRouter(prefix="/v1", tags=["social"])

ViewerDep = Annotated[Viewer, Depends(viewer)]
SessionDep = Annotated[Session, Depends(db_session, scope="function")]
ReadModelDep = Annotated[ReadModel, Depends(read_model)]
Write = [Depends(rate_limited(MethodClass.WRITE))]
Read = [Depends(rate_limited(MethodClass.READ))]

INVITE_TTL = timedelta(days=7)
MAX_ACTIVE_INVITES = 5
MAX_INVITES_PER_DAY = 20
MAX_FRIENDS = 500
# Per-sender limits, counted in the database (ADR 0007).
SEND_LIMITS = ((timedelta(hours=1), 20), (timedelta(days=1), 100))

_SUBJECTS: dict[api.ShareKind, tuple[str, int]] = {
    api.ShareKind.ARTIST: ("artists", 1),
    api.ShareKind.RECORDING: ("recordings", 1),
    api.ShareKind.ARTIST_COMPARISON: ("artists", 2),
    api.ShareKind.RECORDING_COMPARISON: ("recordings", 2),
    api.ShareKind.PATH: ("artists", 2),
}


def _time(value: datetime | None) -> str:
    return "" if value is None else value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _audit(session: Session, user_id: str, action: str) -> None:
    users.audit(session, user_id, action, request_id_var.get(), datetime.now(UTC))


def _enabled(request: Request) -> None:
    if not app_state(request).flags.get("friends", True):
        raise ApiError(Status.UNAVAILABLE, "Friends are switched off.", reason="FLAG_OFF")


def _moderate(request: Request, text: str, field: str) -> None:
    """Runs user text through the moderation hook.

    Raises:
        ApiError: INVALID_ARGUMENT with the moderator's reason.
    """
    verdict: Verdict = app_state(request).moderator.check(text)
    if not verdict.allowed:
        raise invalid_argument(
            "This text can't be sent. Links and hidden characters aren't allowed.",
            field=field,
            reason=verdict.reason or "TEXT_REJECTED",
        )


def _require_name(session: Session, user_id: str) -> str:
    name = social.display_name(session, user_id)
    if not name:
        raise ApiError(
            Status.FAILED_PRECONDITION,
            "Pick the name your friends will see first.",
            reason="DISPLAY_NAME_REQUIRED",
        )
    return name


def _person(user_id: str, names: dict[str, str]) -> api.Person:
    return api.Person(user=f"users/{user_id}", display_name=names.get(user_id, ""))


def _user_id(value: str, field: str) -> str:
    return parse_name(value, "users", field=field)


# ---------------------------------------------------------------------------
# Display name
# ---------------------------------------------------------------------------


@router.get(
    "/users/{user:rid}/socialProfile",
    response_model=api.SocialProfile,
    summary="GetSocialProfile",
    dependencies=Read,
)
def get_social_profile(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.SocialProfile:
    """Returns the name the user shows to friends (empty until picked)."""
    _enabled(request)
    user_id = authorize_user(user, who)
    _private(response)
    return api.SocialProfile(
        name=f"users/{user_id}/socialProfile",
        display_name=social.display_name(session, user_id) or "",
    )


@router.patch(
    "/users/{user:rid}/socialProfile",
    response_model=api.SocialProfile,
    summary="UpdateSocialProfile",
    dependencies=Write,
)
def update_social_profile(
    user: str,
    body: api.UpdateSocialProfileRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.SocialProfile:
    """Sets the name friends see. It passes the moderation hook like notes do."""
    _enabled(request)
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    name = " ".join(body.display_name.split())
    if not name:
        raise invalid_argument("A name is required.", field="displayName")
    _moderate(request, name, "displayName")
    row = social.set_display_name(session, user_id, name, datetime.now(UTC))
    _audit(session, user_id, "socialProfile.update")
    _private(response)
    return api.SocialProfile(name=f"users/{user_id}/socialProfile", display_name=row.display_name)


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


def _invite(row: m.FriendInvite, code: str = "") -> api.FriendInvite:
    return api.FriendInvite(
        name=f"users/{row.user_id}/friendInvites/{row.id}",
        code=invites.display(code) if code else "",
        create_time=_time(row.created_at),
        expire_time=_time(row.expires_at),
    )


@router.get(
    "/users/{user:rid}/friendInvites",
    response_model=api.ListFriendInvitesResponse,
    summary="ListFriendInvites",
    dependencies=Read,
)
def list_friend_invites(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.ListFriendInvitesResponse:
    """Lists the user's open invites. Codes are not shown again (only hashes are kept)."""
    _enabled(request)
    user_id = authorize_user(user, who)
    rows = social.active_invites(session, user_id, datetime.now(UTC))
    _private(response)
    return api.ListFriendInvitesResponse(friend_invites=[_invite(r) for r in rows])


@router.post(
    "/users/{user:rid}/friendInvites",
    response_model=api.FriendInvite,
    summary="CreateFriendInvite",
    dependencies=Write,
)
def create_friend_invite(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.FriendInvite:
    """Creates a single-use invite, valid for 7 days. The code is in this response only."""
    _enabled(request)
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    _require_name(session, user_id)
    now = datetime.now(UTC)
    if len(social.active_invites(session, user_id, now)) >= MAX_ACTIVE_INVITES:
        raise ApiError(
            Status.FAILED_PRECONDITION,
            f"You can have {MAX_ACTIVE_INVITES} open invites; revoke one first.",
            reason="TOO_MANY_INVITES",
        )
    if social.invites_created_since(session, user_id, now - timedelta(days=1)) >= (
        MAX_INVITES_PER_DAY
    ):
        raise ApiError(
            Status.RESOURCE_EXHAUSTED,
            "That's a lot of invites for one day; try again tomorrow.",
            reason="INVITE_LIMIT",
        )
    code = invites.new_code()
    row = social.add_invite(session, user_id, invites.code_hash(code), now, now + INVITE_TTL)
    _audit(session, user_id, "friendInvite.create")
    _private(response)
    return _invite(row, code)


@router.delete(
    "/users/{user:rid}/friendInvites/{invite:rid}",
    response_model=api.Empty,
    summary="DeleteFriendInvite",
    dependencies=Write,
)
def delete_friend_invite(
    user: str,
    invite: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.Empty:
    """Revokes an invite: its code stops working at once."""
    _enabled(request)
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    if not social.delete_invite(session, user_id, invite):
        raise not_found(f"users/{user_id}/friendInvites/{invite}", reason="INVITE_NOT_FOUND")
    _audit(session, user_id, "friendInvite.delete")
    _private(response)
    return api.Empty()


def _usable_invite(session: Session, code: str, user_id: str, now: datetime) -> m.FriendInvite:
    """Finds an invite this user may accept.

    Expired, revoked, unknown, own, deleted-inviter and blocked-either-way invites
    all look the same ("not valid"), so a block is never revealed.

    Raises:
        ApiError: NOT_FOUND (INVITE_NOT_VALID).
    """
    normalized = invites.normalize(code)
    row = (
        None
        if normalized is None
        else social.find_invite(session, invites.code_hash(normalized), now)
    )
    if (
        row is None
        or row.user_id == user_id
        or users.get_live_user(session, row.user_id) is None
        or social.is_blocked_either_way(session, user_id, row.user_id)
    ):
        raise ApiError(
            Status.NOT_FOUND,
            "This invite isn't valid. It may have expired or been used.",
            reason="INVITE_NOT_VALID",
        )
    return row


@router.get(
    "/friendInvites/{code:rid}",
    response_model=api.FriendInvitePreview,
    summary="GetFriendInvite",
    dependencies=Read,
)
def get_friend_invite(
    code: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.FriendInvitePreview:
    """Shows who an invite is from, so the listener can decide. Requires sign-in."""
    _enabled(request)
    user_id = authorize_user("me", who)
    row = _usable_invite(session, code, user_id, datetime.now(UTC))
    names = social.display_names(session, [row.user_id])
    _private(response)
    return api.FriendInvitePreview(
        inviter=_person(row.user_id, names),
        expire_time=_time(row.expires_at),
        already_friends=social.are_friends(session, user_id, row.user_id),
    )


@router.post(
    "/friendInvites/{code:rid}:accept",
    response_model=api.Friend,
    summary="AcceptFriendInvite",
    dependencies=Write,
)
def accept_friend_invite(
    code: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.Friend:
    """Accepts an invite: both become friends, and the code is used up."""
    _enabled(request)
    user_id = authorize_user("me", who)
    check_write_origin(request, who)
    _require_name(session, user_id)
    now = datetime.now(UTC)
    row = _usable_invite(session, code, user_id, now)
    inviter = row.user_id
    if social.are_friends(session, user_id, inviter):
        raise ApiError(Status.ALREADY_EXISTS, "You're already friends.", reason="ALREADY_FRIENDS")
    if (
        social.friend_count(session, user_id) >= MAX_FRIENDS
        or social.friend_count(session, inviter) >= MAX_FRIENDS
    ):
        raise ApiError(
            Status.FAILED_PRECONDITION,
            f"Friends lists are limited to {MAX_FRIENDS} people.",
            reason="TOO_MANY_FRIENDS",
        )
    social.delete_invite(session, inviter, row.id)
    social.befriend(session, user_id, inviter, now)
    _audit(session, user_id, "friend.add")
    _audit(session, inviter, "friend.add")
    names = social.display_names(session, [inviter])
    _private(response)
    return api.Friend(
        name=f"users/{user_id}/friends/{inviter}",
        person=_person(inviter, names),
        create_time=_time(now),
    )


# ---------------------------------------------------------------------------
# Friends
# ---------------------------------------------------------------------------


@router.get(
    "/users/{user:rid}/friends",
    response_model=api.ListFriendsResponse,
    summary="ListFriends",
    dependencies=Read,
)
def list_friends(
    user: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    page_size: PageSize = 100,
    page_token: PageToken = "",
) -> api.ListFriendsResponse:
    """Lists friends, oldest friendship first."""
    _enabled(request)
    user_id = authorize_user(user, who)
    rows = social.friends(session, user_id)
    page = paginate(
        rows, page_size=page_size, page_token=page_token, version="friends", params=user_id
    )
    names = social.display_names(session, [r.friend_id for r in page.items])
    _private(response)
    return api.ListFriendsResponse(
        friends=[
            api.Friend(
                name=f"users/{user_id}/friends/{r.friend_id}",
                person=_person(r.friend_id, names),
                create_time=_time(r.created_at),
            )
            for r in page.items
        ],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
    )


@router.delete(
    "/users/{user:rid}/friends/{friend:rid}",
    response_model=api.Empty,
    summary="DeleteFriend",
    dependencies=Write,
)
def delete_friend(
    user: str,
    friend: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.Empty:
    """Ends a friendship for both people. Shares already sent stay in inboxes."""
    _enabled(request)
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    friend_id = _user_id(friend, "name")
    if not social.unfriend(session, user_id, friend_id):
        raise not_found(f"users/{user_id}/friends/{friend_id}", reason="FRIEND_NOT_FOUND")
    _audit(session, user_id, "friend.delete")
    _private(response)
    return api.Empty()


# ---------------------------------------------------------------------------
# Blocked people
# ---------------------------------------------------------------------------


@router.get(
    "/users/{user:rid}/blockedUsers",
    response_model=api.ListBlockedUsersResponse,
    summary="ListBlockedUsers",
    dependencies=Read,
)
def list_blocked_users(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.ListBlockedUsersResponse:
    """Lists people the user blocked."""
    _enabled(request)
    user_id = authorize_user(user, who)
    rows = social.blocks(session, user_id)
    names = social.display_names(session, [r.blocked_user_id for r in rows])
    _private(response)
    return api.ListBlockedUsersResponse(
        blocked_users=[
            api.BlockedUser(
                name=f"users/{user_id}/blockedUsers/{r.blocked_user_id}",
                person=_person(r.blocked_user_id, names),
                create_time=_time(r.created_at),
            )
            for r in rows
        ]
    )


@router.post(
    "/users/{user:rid}/blockedUsers",
    response_model=api.BlockedUser,
    summary="CreateBlockedUser",
    dependencies=Write,
)
def create_blocked_user(
    user: str,
    body: api.CreateBlockedUserRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.BlockedUser:
    """Blocks someone you know: the friendship ends and shares between you disappear.

    The other person is not told. Neither of you can see, invite or share with the other.
    """
    _enabled(request)
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    other = _user_id(body.user, "user")
    names = social.display_names(session, [other])
    if other in {b.blocked_user_id for b in social.blocks(session, user_id)}:
        raise ApiError(Status.ALREADY_EXISTS, "Already blocked.", reason="ALREADY_BLOCKED")
    if other == user_id or not social.has_contact(session, user_id, other):
        raise not_found(f"users/{other}", reason="PERSON_NOT_FOUND")
    now = datetime.now(UTC)
    social.block(session, user_id, other, now)
    _audit(session, user_id, "userBlock.create")
    _private(response)
    return api.BlockedUser(
        name=f"users/{user_id}/blockedUsers/{other}",
        person=_person(other, names),
        create_time=_time(now),
    )


@router.delete(
    "/users/{user:rid}/blockedUsers/{blocked:rid}",
    response_model=api.Empty,
    summary="DeleteBlockedUser",
    dependencies=Write,
)
def delete_blocked_user(
    user: str,
    blocked: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.Empty:
    """Unblocks someone. You aren't friends again until one of you sends a new invite."""
    _enabled(request)
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    other = _user_id(blocked, "name")
    if not social.unblock(session, user_id, other):
        raise not_found(f"users/{user_id}/blockedUsers/{other}", reason="BLOCK_NOT_FOUND")
    _audit(session, user_id, "userBlock.delete")
    _private(response)
    return api.Empty()


# ---------------------------------------------------------------------------
# Shares and the inbox
# ---------------------------------------------------------------------------


def _subjects(session: Session, model: ReadModel, names: list[str]) -> list[api.SharedSubject]:
    resolved = []
    for name in names:
        collection, _, entity_id = name.partition("/")
        display = ""
        if collection == "artists" and entity_id in model.graph.nodes:
            display = model.graph.nodes[entity_id].name
        elif collection == "recordings":
            recording = session.get(m.Recording, entity_id)
            display = recording.title if recording is not None else ""
        resolved.append(api.SharedSubject(name=name, display_name=display, available=bool(display)))
    return resolved


def _share(session: Session, model: ReadModel, row: m.Share, names: dict[str, str]) -> api.Share:
    return api.Share(
        name=f"shares/{row.id}",
        sender=_person(row.sender_id, names),
        recipient=_person(row.recipient_id, names),
        kind=api.ShareKind(row.kind),
        subjects=_subjects(session, model, list(row.subjects)),
        note=row.note,
        create_time=_time(row.created_at),
        read=row.read_at is not None,
    )


def _check_subjects(
    session: Session, model: ReadModel, kind: api.ShareKind, raw: list[str]
) -> list[str]:
    """Validates subjects against the kind and the catalog; returns resource names.

    Raises:
        ApiError: INVALID_ARGUMENT for the wrong count or type; NOT_FOUND for unknown ones.
    """
    collection, count = _SUBJECTS[kind]
    if len(raw) != count:
        raise invalid_argument(f"{kind.value} takes {count} subject(s).", field="subjects")
    ids = [parse_name(s, collection, field="subjects") for s in raw]
    if count == 2 and ids[0] == ids[1]:  # noqa: PLR2004 (pairs)
        raise invalid_argument("Pick two different subjects.", field="subjects")
    for entity_id in ids:
        known = (
            entity_id in model.graph.nodes
            if collection == "artists"
            else session.get(m.Recording, entity_id) is not None
        )
        if not known:
            raise not_found(f"{collection}/{entity_id}", reason="SUBJECT_NOT_FOUND")
    return [f"{collection}/{i}" for i in ids]


@router.post("/shares", response_model=api.Share, summary="CreateShare", dependencies=Write)
def create_share(
    body: api.CreateShareRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> api.Share:
    """Sends an artist, song, comparison or path to a friend, with an optional note."""
    _enabled(request)
    user_id = authorize_user("me", who)
    check_write_origin(request, who)
    _require_name(session, user_id)
    recipient = _user_id(body.recipient, "recipient")
    # Not friends (including blocked, which ends the friendship) looks like "no such friend".
    if recipient == user_id or not social.are_friends(session, user_id, recipient):
        raise not_found(f"users/{recipient}", reason="FRIEND_NOT_FOUND")
    subjects = _check_subjects(session, model, body.kind, body.subjects)
    note = body.note.strip()
    if note:
        _moderate(request, note, "note")
    now = datetime.now(UTC)
    for window, limit in SEND_LIMITS:
        if social.shares_sent_since(session, user_id, now - window) >= limit:
            raise ApiError(
                Status.RESOURCE_EXHAUSTED,
                "You've shared a lot recently; try again later.",
                reason="SHARE_LIMIT",
                metadata={"windowSeconds": str(int(window.total_seconds()))},
            )
    row = social.add_share(
        session,
        sender_id=user_id,
        recipient_id=recipient,
        kind=body.kind.value,
        subjects=subjects,
        note=note,
        now=now,
    )
    _audit(session, user_id, "share.create")
    names = social.display_names(session, [user_id, recipient])
    _private(response)
    return _share(session, model, row, names)


@router.get(
    "/users/{user:rid}/inbox",
    response_model=api.ListInboxResponse,
    summary="ListInbox",
    dependencies=Read,
)
def list_inbox(
    user: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
    page_size: PageSize = 50,
    page_token: PageToken = "",
) -> api.ListInboxResponse:
    """Lists shares received, newest first.

    Shares about an artist the listener blocked are left out (US-17 applies here too).
    """
    _enabled(request)
    user_id = authorize_user(user, who)
    blocked_artists = {f"artists/{a}" for a in who.blocked}
    rows = [r for r in social.inbox(session, user_id) if not blocked_artists & set(r.subjects)]
    page = paginate(
        rows, page_size=page_size, page_token=page_token, version="inbox", params=user_id
    )
    names = social.display_names(session, list({user_id, *(r.sender_id for r in page.items)}))
    _private(response)
    return api.ListInboxResponse(
        shares=[_share(session, model, r, names) for r in page.items],
        next_page_token=page.next_page_token,
        total_size=page.total_size,
        unread_count=sum(1 for r in rows if r.read_at is None),
    )


def _received(session: Session, share: str, user_id: str) -> m.Share:
    share_id = parse_name(share, "shares", field="name")
    row = social.get_share(session, share_id)
    if row is None or row.recipient_id != user_id:
        raise not_found(f"shares/{share_id}", reason="SHARE_NOT_FOUND")
    return row


@router.post(
    "/shares/{share:rid}:markRead",
    response_model=api.Share,
    summary="MarkShareRead",
    dependencies=Write,
)
def mark_share_read(
    share: str,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
    model: ReadModelDep,
) -> api.Share:
    """Marks a received share read."""
    _enabled(request)
    user_id = authorize_user("me", who)
    check_write_origin(request, who)
    row = _received(session, share, user_id)
    social.mark_read(session, row, datetime.now(UTC))
    names = social.display_names(session, [row.sender_id, user_id])
    _private(response)
    return _share(session, model, row, names)


@router.post(
    "/users/{user:rid}/inbox:markRead",
    response_model=api.MarkAllReadResponse,
    summary="MarkInboxRead",
    dependencies=Write,
)
def mark_inbox_read(
    user: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.MarkAllReadResponse:
    """Marks every share in the inbox read."""
    _enabled(request)
    user_id = authorize_user(user, who)
    check_write_origin(request, who)
    marked = social.mark_all_read(session, user_id, datetime.now(UTC))
    _private(response)
    return api.MarkAllReadResponse(marked=marked)


@router.delete(
    "/shares/{share:rid}", response_model=api.Empty, summary="DeleteShare", dependencies=Write
)
def delete_share(
    share: str, request: Request, response: Response, who: ViewerDep, session: SessionDep
) -> api.Empty:
    """Removes a share. The recipient clears it from their inbox; the sender can unsend it."""
    _enabled(request)
    user_id = authorize_user("me", who)
    check_write_origin(request, who)
    share_id = parse_name(share, "shares", field="name")
    row = social.get_share(session, share_id)
    if row is None or user_id not in {row.recipient_id, row.sender_id}:
        raise not_found(f"shares/{share_id}", reason="SHARE_NOT_FOUND")
    social.delete_share(session, row)
    _audit(session, user_id, "share.delete")
    _private(response)
    return api.Empty()


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@router.post("/reports", response_model=api.Report, summary="CreateReport", dependencies=Write)
def create_report(
    body: api.CreateReportRequest,
    request: Request,
    response: Response,
    who: ViewerDep,
    session: SessionDep,
) -> api.Report:
    """Reports a share you received (it leaves your inbox) or a person you know.

    Moderators see a copy of the reported note; reports are kept 90 days. Blocking
    is a separate step, so reporting alone never tips anyone off.
    """
    _enabled(request)
    user_id = authorize_user("me", who)
    check_write_origin(request, who)
    if bool(body.share) == bool(body.user):
        raise invalid_argument("Report either a share or a person.", field="share")
    now = datetime.now(UTC)
    report = m.AbuseReport(
        id="",
        reporter_id=user_id,
        reason=body.reason.value,
        details=body.details.strip(),
        status="OPEN",
        created_at=now,
    )
    if body.share:
        row = _received(session, body.share, user_id)
        report.reported_user_id = row.sender_id
        report.share_kind = row.kind
        report.share_subjects = list(row.subjects)
        report.share_note = row.note
        social.delete_share(session, row)
    else:
        other = _user_id(body.user, "user")
        if other == user_id or not (
            social.has_contact(session, user_id, other)
            or social.is_blocked_either_way(session, user_id, other)
        ):
            raise not_found(f"users/{other}", reason="PERSON_NOT_FOUND")
        report.reported_user_id = other
    social.add_report(session, report)
    _audit(session, user_id, "report.create")
    _private(response)
    return api.Report(name=f"reports/{report.id}", reason=body.reason, create_time=_time(now))
