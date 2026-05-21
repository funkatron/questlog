# Screenshot Fixtures

Selected from `/Volumes/T7-1TB/TimeSnapper-imgs/2026-04-27` to keep OCR and
backfill experiments fast and repeatable.

Fixture JPGs are stored in Git LFS. After clone, run `git lfs pull` if images are missing locally.

Use [targets.json](/Users/coj/src/questlog/tests/fixtures/screenshots/targets.json)
as the evaluation baseline. It distinguishes between the likely frontmost app
and the visible activity on screen, because those are not always the same.

## Included fixtures

- `slack-checkin-message.jpg`
  - Source: `2026-04-27--15-25-00 UTC.jpg`
  - Visible activity: Slack conversation / check-in

- `safari-youtube-icloud-tabs.jpg`
  - Source: `2026-04-27--15-26-00 UTC.jpg`
  - Visible activity: Safari with iCloud tab overview on the left and YouTube on the right
  - Important: the menu bar suggests `Draw Things` may have been the frontmost app, but the visible windows are browser content

- `zoom-workplace-linear.jpg`
  - Source: `2026-04-27--15-32-09 UTC.jpg`
  - Visible activity: Zoom meeting with Linear issue list visible

- `cursor-editor-terminal.jpg`
  - Source: `2026-04-27--15-34-09 UTC.jpg`
  - Visible activity: Cursor/editor workspace with terminal controls

- `linear-issues-zoom-sidebar.jpg`
  - Source: `2026-04-27--15-35-09 UTC.jpg`
  - Visible activity: Linear issues view with Zoom participant sidebar

## Why These

- Small set for quick iteration
- Mix of easy and hard app-inference cases
- Covers chat, browser/media, meeting, editor, and work-tracking screens
- Includes one case where frontmost-app and visible-content signals diverge
