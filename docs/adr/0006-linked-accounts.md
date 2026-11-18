# ADR 0006: Linked listening accounts

- **Status:** Accepted, 2026-11-04 (R2-6).
- **Context:** Listeners want their history to flow in without exporting files (story S7). The reference build must
  work with every service that offers a legitimate way in, without scraping or unofficial APIs, and the design must
  carry over to YouTube Music, where history is first-party. Checked 2026-11-04:

  | Service | Way in | Ownership proof | Notes |
  |---|---|---|---|
  | ListenBrainz | Public listens API | User token, validated with `validate-token` | Open; no app key needed |
  | Last.fm | `user.getRecentTracks` | Web authentication (`auth.getSession`) | Needs an API key and secret |
  | Libre.fm | Last.fm-compatible API | Same as Last.fm | Different base URL |
  | Spotify | `me/player/recently-played` (last 50), `me/top/artists` | OAuth 2 with PKCE | Development mode caps allow-listed users; policy question for a Google product |
  | Deezer | `user/me/history` | OAuth (`listening_history` permission) | New-app registration unconfirmed: off until tested |
  | Apple Music | `me/recent/played/tracks` | MusicKit user token | Needs a paid Apple developer token |
  | Tidal | No history API (an open request on TIDAL's developer forum) | — | Tidal can scrobble to Last.fm: link Last.fm |
  | YouTube Music | No public history API; liked songs via YouTube Data API `videos?myRating=like` (music category) | Google OAuth 2 with PKCE, `youtube.readonly` | Each liked song counts once; Takeout import without a Google client; first-party adapter in production |
  | Amazon Music | No public history API | — | Not supported |

- **Decision:**
  1. One connector interface (`accounts/connectors.py`): `fetch(credentials, cursor) -> (plays, next cursor)`.
     Every provider implements it; YouTube Music's first-party adapter is a stub with contract tests, so the
     integrating team implements one class.
  2. **Data minimization.** Plays are resolved to catalog artists on the server with the import matcher (ambiguous
     names are not auto-matched) and stored only as per-artist aggregates: play count and last played time. Track
     titles, timestamps of individual plays, and unmatched names are not stored; unmatched plays are counted.
  3. **Tokens are encrypted at rest** with AES-256-GCM under a key that never sits in the database
     (`SONGNEXUS_TOKEN_KEY` in development, Secret Manager or KMS in production), with a key ID prefix for rotation.
     Tokens are never logged or returned by the API.
  4. **OAuth state** (state value, PKCE verifier) is held server-side, bound to the session that started the flow,
     single use, and expires after 10 minutes.
  5. **Sync** runs as a scheduled job every 15 minutes plus "Sync now", incremental by cursor, with per-provider
     backoff. The UI says "synced N minutes ago", never "real time".
  6. **Disconnect deletes** the token and every aggregate synced from that account in the same transaction.
     Export includes linked accounts (provider, user name, linked and synced times; never tokens) and their
     aggregates; account deletion removes them.
  7. Each provider is behind a feature flag and is offered only when its keys are configured.
  8. **YouTube Music** links through Google (liked songs, read-only scope) when a Google OAuth client is
     configured, and falls back to on-device Takeout import otherwise. Likes carry no time, so the cursor is the
     newest video IDs seen; a liked song is one play.
  9. **Development needs no setup:** without `SONGNEXUS_TOKEN_KEYS`, development generates a key into a
     git-ignored file; `POST /v1/sessions:local` signs in without Firebase (development only, NOT_FOUND
     elsewhere); `SONGNEXUS_SYNC_IN_PROCESS=true` runs the 15-minute job inside the API. Deployed environments
     schedule `songnexus sync-accounts` and must configure keys.
- **Consequences:** a provider's terms can change without warning (Spotify's did in 2024 and 2025), so each
  connector is isolated, flagged, and covered by contract tests against recorded responses. The minimization means
  the product cannot show "what you played on Tuesday"; that is deliberate for R2.
