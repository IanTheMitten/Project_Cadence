# Hardware progress

Where the physical side of Cadence is tracked: what is built, what was measured, what is next. Code state lives in git; hardware state does not, so it is recorded here.

| File | Purpose |
|---|---|
| `build-log.md` | Dated journal, newest first. One entry per bench session, wiring change, flash, or measurement. |
| `inventory.md` | Boards, parts, wiring, and what each is currently flashed with. Update in place. |
| `measurements/` | Raw numbers, graphs, photos, and captures, named `YYYY-MM-DD-<topic>.<ext>`. |

Planned work, not yet done, stays in `docs/specs/` (`2026-10-07-speaker-hardware-improvements.md`, `2026-10-13-csi-ground-tests.md`). When a spec item is done, log it in `build-log.md` and link the spec section.

## Rules

- Log the same day the work happens, and commit and push it (see "Version control and multi-machine sync" in `CLAUDE.md`).
- Record facts: what changed, what firmware or project directory, which board, the result. Include failures and dead ends.
- Numbers need units and conditions (distance, volume, room, power source). Mark values as `measured` or `derived from code`.
- Keep photos small (under about 1 MB) and in `measurements/`. No WiFi credentials or private data in photos.
- Status words: `planned`, `in progress`, `working`, `broken`, `abandoned`.
