# ADR 0002: Server-side sessions instead of Firebase session cookies

- **Status:** Accepted, 2026-10-07. Supersedes the "Firebase session cookie" detail in plan §13 F1.
- **Context:** After Google Sign-In, the browser holds a short-lived Firebase ID token. The plan proposed exchanging it
  for a Firebase *session cookie* (`createSessionCookie`). That ties every request to the Firebase Admin SDK and a live
  Firebase project, makes revocation depend on Firebase's revocation check, and is awkward to test hermetically.
- **Decision:** The server verifies the ID token once (Firebase Admin SDK, or the Auth emulator locally), then creates
  its own session:
  - a 256-bit random token in an `HttpOnly; Secure; SameSite=Lax` cookie;
  - only the token's SHA-256 hash is stored, with user, expiry (14 days) and last-seen time;
  - sign-out deletes the row; "sign out everywhere" deletes all of the user's rows;
  - writes require an `X-CSRF-Token` header matching a per-session token, plus an allowed `Origin`.
- **Consequences:** sessions are revocable instantly, fully testable without network, and independent of Firebase
  beyond sign-in. We own expiry and cleanup (a purge job deletes expired rows).

## Amendment 1 (2026-10-07): cookie name

Firebase Hosting forwards only a cookie named `__session` to Cloud Run rewrites and strips all others (it also
adds `__session` to its CDN cache key). The session cookie is therefore `__session` rather than
`__Host-songnexus_session`. It keeps every protection the `__Host-` prefix implied: `Secure`, `HttpOnly`,
`SameSite=Lax`, `Path=/` and no `Domain` attribute (host-only). Found in QA review Q1.
