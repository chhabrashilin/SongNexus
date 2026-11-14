# Linked-account sync failures

**Symptom:** listeners say "synced N minutes ago" keeps growing, links show "Access expired. Reconnect", or linking
fails with an error page from the provider.

**Confirm:** run the job by hand and read its counts: `uv run songnexus sync-accounts` prints what it synced,
what failed and what needs relinking. In the database:

```sql
SELECT provider, status, count(*), max(failures), min(next_sync_after)
FROM linked_accounts GROUP BY provider, status;
SELECT provider, last_error, count(*) FROM linked_accounts
WHERE failures > 0 GROUP BY provider, last_error ORDER BY 3 DESC;
```

**Mitigate:**
- **One provider failing for everyone** (outage, quota, changed API): nothing to do at first. Backoff doubles up to
  24 h and links are kept. If it lasts, unset that provider's keys (it then shows "Not set up on this server yet")
  or switch the whole feature off with `SONGNEXUS_FLAGS={"linkedAccounts": false}`.
- **Spotify or Google refresh failing** (`invalid_grant`): the user revoked access or the client secret rotated.
  Revoked links become NEEDS_RELINK by design and the user sees "Reconnect". If every link fails at once, check
  `SONGNEXUS_SPOTIFY_CLIENT_ID`, `SONGNEXUS_GOOGLE_CLIENT_ID` and `SONGNEXUS_GOOGLE_CLIENT_SECRET`.
- **`redirect_uri_mismatch` when linking:** the provider app must list exactly
  `{SONGNEXUS_APP_ORIGIN}/v1/oauth/{provider}/callback` (for example `.../v1/oauth/youtube_music/callback`). Fix it
  in the provider console; nothing changes server-side.
- **Decryption errors** (`InvalidTag`): the token key changed. Put the previous key back under its old ID in
  `SONGNEXUS_TOKEN_KEYS` and keep the new one as `SONGNEXUS_TOKEN_KEY_ID`. Never delete a key that still has
  ciphertexts.
- **YouTube Data API quota:** each liked-songs page costs one unit and the job reads at most 20 pages per account
  per run. Raise the quota or lengthen the interval before raising the page cap.

**Follow-up:** a provider that changed its API needs a connector fix and a contract test with the new response
(`tests/accounts/test_connectors.py`). Record outages longer than a day in the postmortem log.
