# Handoff — Muse ↔ Cadence contract (for planning in `muse_intelligence`)

**Use:** open a session in `~/Projects/muse_intelligence` and hand it this file as the goal for
a plan. It describes what Cadence needs from Muse and the ground rules both sides follow. It does
not prescribe Muse's internal design; that session reads Muse's own `CLAUDE.md`, `PRODUCT.md`, and
`docs/adrs/` first and plans in Muse's conventions.

Source of the rules: `Cadence_Speaker/docs/specs/2026-10-01-cadence-decision-harness-v1.md`,
decisions "Muse–Cadence contract, owned by Muse" and "Speaker and Muse sync through shared facts".

## Why

Cadence is the home voice system (ESP32 speaker, later a lamp). Its harness plays music from Muse
on the speaker. The user's requirement: **changes in Muse must not break Cadence, and the reverse,
and the rules are documented in Muse too.**

## Ground rules (agreed on the Cadence side)

1. **Muse owns the contract.** Muse is the provider; the contract lives in the Muse repo.
2. **Documented surface.** `docs/contracts/cadence.md` in Muse lists every endpoint Cadence uses
   (the "Cadence surface", below), with request and response shapes and meaning.
3. **Snapshot test.** A committed OpenAPI snapshot of the Cadence surface, plus a Muse test that
   diffs the live app's OpenAPI for those paths against it. Changing the surface fails Muse's tests
   until the snapshot, the doc, and the version are updated on purpose.
4. **Versioned.** `GET /api/contract` returns `{"version": "MAJOR.MINOR"}`, starting at `"1.0"`.
   Additive change (new optional field, new endpoint) bumps minor. Rename, removal, type change, or
   changed meaning bumps major, and the old behaviour stays available for a deprecation window.
5. **Change flow.** A surface change lands in Muse first (code, snapshot, doc, version), then Cadence
   syncs. Both repos' `CLAUDE.md` say so. Record the rule as a Muse ADR.
6. **Cadence's side (already planned there):** Cadence calls `GET /api/contract` at startup.
   404 means "pre-contract baseline" (today's API) and is accepted. Major `1` is accepted. Any other
   major disables music in Cadence (it says "Muse isn't answering") without crashing. Cadence ignores
   unknown response fields, so adding fields is always safe.

## The Cadence surface (what Cadence calls today and in v1)

| Endpoint | Caller | Used fields |
|---|---|---|
| `GET /api/library/search?q&limit` | music plugin | `results[]`: `track_rowid`, `track_name`, `artist_name`, `artist_names`, `duration_ms`, `playable` |
| `GET /api/library/search/vibe?q&n` | music plugin | `results[]`: `track_rowid`, `score`, `track{same fields}` |
| `POST /api/ratings` `{track_rowid, rating: 1\|-1\|null}` | music plugin | status only |
| `POST /api/plays` `{track_rowid, duration_ms, source}` | music plugin, `source = "cadence"` | `id` |
| `POST /api/plays/{id}/close` `{ended_reason, position_ms}` | music plugin | status only |
| `GET /api/tracks/{id}/stream` | `tools/muse_proxy.py` (transcodes to PCM via ffmpeg) | audio body |
| `GET /api/contract` | Cadence startup | `version` (new endpoint, see below) |
| `GET /api/recommend/{id}`, `GET`/`PUT /api/player/state`, `GET /api/dashboard` | M1 Muse MCP server (in the Cadence repo, unwired in v1) | as in Cadence `harness/tests/fixtures/muse/` |

`ended_reason` values Cadence sends: `track_end`, `user_next`, `user_prev`, `new_selection`,
`pause_timeout`, `lost` (exactly Muse's `ENDED_REASONS`, `muse/api.py:138`). Cadence maps "stop the
music" to a pause, and a pause longer than 600 s closes the span with `pause_timeout`. **Adding or
renaming an ended reason is a major change** for Cadence; per ADR 0001, `plays` is the table that
cannot be regenerated.

Cadence keeps the speaker's own queue and does **not** use `/api/player/state` in v1 (the phone and
the speaker must not hijack each other's playback). Shared facts are plays and ratings only.

## Deliverables for the Muse plan

1. `docs/contracts/cadence.md` — the surface above, rules 1–6, and how to bump the version.
2. OpenAPI snapshot of the Cadence surface (committed) plus the snapshot-diff test, in Muse's
   default test run.
3. `GET /api/contract` → `{"version": "1.0"}`, added to the surface and snapshot.
4. An ADR recording "Muse owns the Cadence contract" and the versioning rule.
5. A `CLAUDE.md` note pointing at the contract doc and saying surface changes go Muse-first.

## Later additions Cadence wants (each a minor bump, not needed for v1)

- **Filtered vibe search:** vibe search restricted to an artist (for "upbeat Justin Bieber"). Cadence
  currently fakes this by intersecting text and vibe results client-side; a server-side filter makes
  it exact. Cadence's `music.play` capability does not change when this lands.
- **Saved, named playlists:** create, list, and fetch a playlist of track ids, so "save this as my
  focus playlist" and "play my focus playlist" work. Cadence adds a `music.playlist` capability then.
- **Recommendation algorithm fixes:** the user wants them; specifics have not been gathered yet.
  Ask the user before planning that part.

## Constraints and facts for the Muse session

- Muse binds tailnet addresses only (`muse/net.py`); Cadence reaches it at `100.122.149.75:8080`.
- There is a worktree with changes in progress at `.claude/worktrees/universal-reco-content-embed/`.
  Check its state before touching `muse/api.py`.
- Read `docs/adrs/0001-plays-stores-physical-fact.md` before touching plays.
- Cadence's captured fixtures of today's responses live in
  `Cadence_Speaker/harness/tests/fixtures/muse/` (including `openapi.json`), and are a useful
  cross-check for the snapshot.
