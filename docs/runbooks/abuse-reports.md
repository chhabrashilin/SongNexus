# Abuse reports and harmful sharing

**Symptom:** reports arrive (`report.create` in the audit log, rows in `abuse_reports`), a listener writes in about
harassment, or one sender keeps hitting `SHARE_LIMIT`.

**Review the queue** at least weekly (reports are purged after 90 days):

```sql
SELECT id, created_at, reason, reported_user_id, share_kind, share_note, details
FROM abuse_reports WHERE status = 'OPEN' ORDER BY created_at;
-- Repeat reports in the last 30 days:
SELECT reported_user_id, count(*) FROM abuse_reports
WHERE created_at > now() - interval '30 days' GROUP BY 1 ORDER BY 2 DESC;
```

**Act:**
- **One mild report:** mark it reviewed (`UPDATE abuse_reports SET status = 'REVIEWED' WHERE id = ...`). The share
  already left the reporter's inbox, and the reporter was offered "also block".
- **Clear abuse, or several reporters:** revoke the person's sessions (`DELETE FROM user_sessions WHERE user_id = ...`)
  and, if warranted, delete the account through the normal deletion path (`users.erase_user`), which also removes
  their shares from every inbox. Record the decision and the report IDs in the moderation log; never paste notes
  into tickets or chat.
- **Link spam getting past the rules:** find the pattern, add it to `social/moderation.py` with a test, and deploy.
  To stop all sharing at once, set `SONGNEXUS_FLAGS={"friends": false}`; inboxes and invites go dark until it is
  switched back.
- **Threats of violence or child-safety concerns:** escalate to the sponsor's trust and safety contact
  immediately, and note the report ID before the 90-day purge removes it.

**Follow-up:** report counts by reason go in the weekly review. A production launch needs a toxicity classifier
behind `Moderator` and a moderator console (security review R2-8, findings R2 and R3).
