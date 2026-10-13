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
