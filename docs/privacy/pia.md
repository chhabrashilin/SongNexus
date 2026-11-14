# Privacy impact assessment (M8-04)

Status: engineering assessment as of 2026-10-13. Legal review of the privacy notice and terms is still required before
any tester access (see the [launch review](../launch-review.md)).

## Data inventory

| Data | Where | Why | Retention |
|---|---|---|---|
| Public music facts (MusicBrainz) | database | the product | until replaced by a new catalog |
| Sign-in identity | Firebase Auth holds the email and profile; the server stores the user ID and display name | account | until deletion |
| Age confirmation (13+) | user row | requirement for use | with the account |
| Session | hash of the session token and its expiry | stay signed in | until expiry or sign-out; expired sessions are purged daily |
| Preferences, blocked artists, top-5 artists | user rows | personalization | until changed, or the account is deleted |
| Listening files and playlists | **never leave the device**; only distinct artist names are sent for matching, and they are not stored or logged | import | none on our side |
| Puzzle progress, theme, language | browser local storage | convenience | until the user clears it |
| Request logs | Cloud Logging: route, status, latency, request ID | operations | log bucket retention (to be set to 30 days at deploy) |
| Share count | aggregate counter in logs, no identity | puzzle health | log retention |

## Principles check

- **Minimization:** no listening history, lyrics or contacts are collected; imports send names only.
- **Consent:** saving anything from an import to the account is a separate, explicit step (US-10).
- **User control:** export (`GET /v1/users/{user}:export`), delete (`DELETE /v1/users/{user}`, purged after 28 days),
  sign out everywhere, per-artist blocking. All are covered by tests.
- **No third-party analytics, ads or trackers.** The third parties are Google (Firebase Auth, Hosting, Cloud Run, Cloud
  SQL) and MusicBrainz (build time only; users never contact it).
- **Children:** users must confirm they are 13 or older.

## Risks and mitigations

| Risk | Mitigation | Residual |
|---|---|---|
| Names in an import reveal taste to the server operator | not stored, not logged (tested); TLS in transit | Low: names exist in memory for one request |
| Request logs reveal client addresses | short retention; no cookies or bodies logged | Low |
| A user's blocks leak to others | blocks apply only to that user's responses (tested, including playlists) | Low |
| Re-identification through the share counter | it has no identity or timing detail | Negligible |
| Deleted accounts persist in backups | backups expire in 7 days and the purge job removes rows after 28 days; say so in the notice | Low |

Open before launch: publish the privacy notice and terms (the in-app Privacy page is the engineering draft), set the
log retention in Cloud Logging, and confirm the data-processing terms for Firebase and GCP with the sponsor's legal
contact.

## Release 2 additions (2026-11-13)

R2 adds two kinds of personal data, under the same rules: aggregates over raw records, export and deletion from
day one, and nothing visible to other people unless the user sends it.

| Data | Where | Why | Retention |
|---|---|---|---|
| Linked-account tokens (ADR 0006) | `linked_accounts`, AES-256-GCM ciphertext, key outside the database | sync listening history | until unlinked or the account is deleted |
| Listening tallies | `listening_tallies`: plays and last play time **per catalog artist**; no track titles, no individual play times; unmatched names only counted | "Your top artists", Library | until unlinked (deletes every tally from that service) or deletion |
| Provider account name | `linked_accounts.external_user` | show which account is linked | as above |
| Display name for friends (ADR 0007) | `social_profiles`, chosen by the user | what friends see | until changed or deletion |
| Friendships, blocks | `friendships`, `user_blocks` | friends list; mutual invisibility | until removed or deletion |
| Invites | `friend_invites`: the **hash** of the code and its expiry | single-use invites | 7 days, then purged daily |
| Shares and notes | `shares`: kind, catalog subjects, note (≤ 140 characters), read time | the inbox | until the recipient or sender removes it, or either account is deleted |
| Abuse reports | `abuse_reports`: reason, details, a copy of the reported note and subjects | moderation | 90 days, then purged daily |

Principles check:
- **Minimization:** linked accounts keep per-artist counts only; YouTube Music reads liked songs with the read-only
  scope; friends see a chosen name and what is shared with them, never listening, profile or linked accounts.
- **Consent and control:** linking is an explicit OAuth or token step, and "Disconnect" deletes the token and every
  tally from that service; friendship needs an invite the other person chose to send; blocking is one tap.
- **Export and deletion:** `users/{user}:export` includes linked accounts (never tokens), tallies, the display name,
  friends, open invites (never codes), blocks, shares sent and received, and reports filed. Deleting an account
  removes all of it at once, including the user's shares from friends' inboxes (tested).
- **Children:** the 13+ confirmation still gates every account. Invite-only friendship limits contact from
  strangers; a launch to teenagers needs the sponsor's child-safety review.

| Risk | Mitigation | Residual |
|---|---|---|
| A database leak exposes provider tokens | encryption under an external key, bound to user and provider | Low while the key stays out of the database |
| Tallies reveal taste to the operator | per-artist counts only, no play timestamps; never shown to friends | Low |
| Unwanted contact or harassment | invites only, silent blocks, reports, rule moderator, send limits | Medium until a classifier is wired ([security review](../security/review-2026-11-13.md), R2) |
| A reported note outlives the sender's account | kept 90 days for moderation, linked to no account after the sender is deleted | Low; say so in the privacy notice |
| Revealing a block | blocked actions fail exactly like invalid ones (tested) | Negligible |

Open before launch, in addition to the list above: the privacy notice must describe linked accounts, the 90-day
report retention and what friends can see; confirm the Spotify and Google API terms allow the stored aggregates.
