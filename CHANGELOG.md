# Changelog

## v0.3.0 (2026-11-10)

- Add **permanent BAN undo** by saved YouTube ban resource ID from the user-history tab.
  Only successful permanent bans are eligible; failed requests remain auditable.
- Require monitoring to be stopped, test mode to be disabled, and confirmation before
  sending `liveChatBans.delete` (200 quota units).
- Add the dashboard's **local estimated API quota used/remaining**, per-method
  breakdown and `quotaExceeded` indicator, with a Google Cloud link for actual usage.
- Add quota tracking for REST API calls and gRPC `streamList` initial connections,
  grouped by OAuth project and Pacific Time day with DST-aware rollover.
- Document differences between local estimates and actual Google Cloud quota;
  do not silently claim the Cloud project's remaining quota is available.
- Preserve the existing SQLite message/action history and existing user settings.
- Add isolated tests for ban lifecycle, quotas, PT resets and separate projects.

## v0.2.1 (2026-11-10)

- Add automatic cleanup of locally observed live-chat messages **after confirmed permanent ban**.
- Add cleanup toggle and optional per-user cap in GUI (`0` = all known messages).
- Stop cleanup on YouTube API errors instead of blindly retrying.
- Preserve local history and store per-message deletion outcome, plus summary actions.
- Migrate existing SQLite DB to new columns without removing message history.
- Add isolated automated tests of cleanup (no YouTube connection required).

## v0.2.0

- Default to YouTube streamList receiving and provide REST polling as fallback.
