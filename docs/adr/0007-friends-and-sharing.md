# ADR 0007: Friends and sharing

- **Status:** Accepted, 2026-11-13 (R2-7).
- **Context:** Listeners want to send each other what they find: an artist, a song, a comparison, a path (story
  S8). On 2026-11-01 the sponsor decided that friends connect **by invite link or code only**. A social feature
  adds abuse surfaces (spam, harassment, unwanted contact), so the design has to make unwanted contact hard by
  default and give people simple ways out.

- **Decision:**
  1. **Invites are the only way in.** There is no user search, no contact upload, no "people you may know" and no
     public directory. An invite is a 10-character Crockford base32 code (50 random bits), shown as `XXXXX-XXXXX`
     and as a link `/friends/join/{code}`. It is **single use**, expires after **7 days**, and can be revoked. Only
     its SHA-256 is stored, so a database leak reveals no usable codes. A user has at most 5 open invites and can
     create 20 a day. Reading a code is forgiving (case, spaces, dashes, O/I/L look-alikes).
  2. **Friends see a chosen display name and what is shared with them, nothing else.** Names come from the user
     (1–40 characters, moderated), never from the identity provider. Profiles, listening and linked accounts stay
     private.
  3. **Sharing needs a friendship.** A share is one of `ARTIST`, `RECORDING`, `ARTIST_COMPARISON`,
     `RECORDING_COMPARISON` or `PATH`, with subjects validated against the catalog and an optional note of at most
     140 characters. Recipients have an inbox with read state; shares about an artist the recipient blocked
     (US-17) are left out.
  4. **Blocking is silent and mutual.** Blocking someone you know (a friend, or someone who shared with you) ends
     the friendship and removes the shares between you in both directions. The other person is not told. Invites
     and shares across a block fail exactly like an expired invite or a non-friend, so a block is never revealed.
     Unblocking does not restore the friendship.
  5. **Moderation hook.** Notes and display names pass `Moderator.check(text)`. The reference build runs
     `RuleModerator`: no links (the main spam and phishing vector), no hidden or bidi-control characters (the
     emoji joiner is allowed), no floods of one character. Production puts a toxicity classifier behind the same
     interface; until one is wired, the rules plus reports and blocking are what runs.
  6. **Limits are counted in the database**, so they hold across instances: 20 shares an hour and 100 a day per
     sender, on top of the per-instance request limits.
  7. **Reports** name a share you received (it leaves your inbox) or a person you know, with a reason. Moderators
     get a copy of the reported note and subjects; reports are purged after **90 days** by the daily purge job.
     Reporting doesn't block automatically; the web offers "also block" in the same step.
  8. **Privacy lifecycle.** Every change is audited (`friend.add`, `share.create`, `userBlock.create`,
     `report.create`, …). Export includes the display name, friends, open invites (never codes), blocks, shares
     sent and received, and reports filed. Deleting an account removes all of it at once, and the user's shares
     leave friends' inboxes immediately. Reports about a deleted user lose the link to them.
  9. **Kill switch:** the `friends` feature flag turns the API (503 `FLAG_OFF`) and every entry point off.

- **Consequences:**
  - Growth is slower than with search or contacts: by design.
  - The rule moderator is narrow; harassment without links gets through until a classifier is wired. Reports,
    blocking and the send limits bound the damage. The abuse runbook covers review.
  - Friendships are stored twice (one row per direction) for one-lookup reads; both rows change together.
  - YouTube Music integration: the invite, block and moderation contracts carry over; production would replace
    display names with the Google account's chosen YouTube handle only if the product decides so.
