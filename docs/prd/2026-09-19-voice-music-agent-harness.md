# PRD — *&lt;working name: unpicked&gt;*

> Status: PRD-complete, pre-planning.
> Routing: technical/architecture questions parked below → spec-brainstorming next, then `/autopilot-plan`.
> Scope: two passes in one effort. Pass one is the box (this document's Features). Pass two is Muse's recommender, specified after the box's architecture settles.

## The spark

> "I want to wire the voice agent with the music player so like agentic AI basically. so it should be wired with the i4nle3@100.122.149.75 music server and use Ollama cloud for the LLMs."

> "I want it to be agentic harness so keep like some expandibility in mind"

## The idea

A voice box that runs your music the way a bartender runs your tab — it knows your usual, reads the room, and mostly acts without being asked. You speak only when it has drifted from what you wanted. Underneath, it is an MCP-style harness: tools are declared to it, and it decides which to call. Music is the only thing it does today, but the wiring is general — later it phones other agents (Claude Code for code) rather than absorbing their jobs. In the user's words: **"you give tools and tell it what to do and it does it. it's an assistant not a worker."**

## Who it's for, and the moment

You, alone, working — barely looking up, occasionally saying "something less sad" and expecting it to land. And you with guests over, where the box is the DJ nobody wants to be: you hand it a vibe, it reads the room.

## The heart

Two things, inseparable:

- **Memory of you** — knows your usual, sharpens over weeks. Not a stateless command parser.
- **Thermostat logic** — mostly invisible, adjusts on its own. You speak only when it drifted.

## Not the obvious version

The obvious version is a voice-controlled music player: wake word, command, response, silence. A local Alexa.

This one **starts without being asked** — reads the hour and what you played last Tuesday at this time, and just goes. It **keeps a diary** you can query: "what was I into last month?" and it names patterns you never noticed. And it has **mild opinions** — "you skip this every time, want it gone?" — dialed down, not a critic.

## Features

### Part one — the box

**Must** *(each traces to the heart or a user pick)*

- **Voice turn that actually acts** — wake word, you speak, it does the thing. The instinct that went nowhere on the bench now lands.
- **Vague input resolves** — "something less sad" becomes real playback through Muse's search/vibe, no title ever needed.
- **Starts unasked** — reads the hour and what you played at this hour before, and just goes. No prompt.
- **Correction is the main input** — "no, not that" steers mid-stream and the rejection sticks for the session. You speak only when it drifted.
- **Tools declared, not hardcoded** — adding a tool never touches the core loop. *"you give tools and tell it what to do and it does it."*
- **Diary queryable and burnable** — "what was I into last month," answered; erased in one command.

**Should** *(cuttable under pressure)*

- Mild opinions — "you skip this every time, want it gone?" Dialed to the user's "a little bit."
- ⚑ *inferred* — solo mode vs guests-over mode; box notices which scene it's in.
- ⚑ *inferred* — box hands context signals (hour, mood words spoken) to Muse so its recommender can use them.

**Won't (this version)**

- Do coding work. Prompts Claude Code, never codes.
- Ship non-music tools. Harness supports them; none ship.
- Listen without a wake word.
- Reach outside the owned library *(soft — user said "maybe")*.

### Part two — Muse recommender

In scope, specified after the box. Held here because the box depends on Muse's API and changing the recommender underneath can break the box's assumptions.

The user's description, verbatim: *"more of a transformer kind of thing so like it doesn't memorize what songs I like but rather what kind of songs I like in what mood and after what kind of song which I want it to have contextual knowledge of both the audio and the lyrics."*

Implementation delegated to Claude Code on `100.122.149.75`. Not decomposed into features here — it has not been sparred.

## Acceptance criteria

*(Part one only. Part two's criteria come after it is sparred.)*

- From across the room, wake + "play something" starts music without touching a device.
- A vague mood request produces playback the user does not immediately correct, most of the time.
- On a typical evening, music starts before the user says anything.
- "Not this one" changes what plays next, and that rejection does not come back that session.
- A new tool can be added and used in conversation without existing music behavior changing.
- The user can ask what they listened to last month, get a real answer, and erase the record in one command.

## Non-goals

Multi-room sync. Multi-user voice ID. Discovery outside the owned library. Replacing the Muse web UI.

~~Real echo cancellation — mic mute stays the blunt mitigation.~~ **Superseded** by `docs/specs/2026-09-19-voice-music-agent-harness.md` (Decision: Echo handling). This non-goal was written when speech was the only output. Music ducking keeps audio playing for minutes while the mic must stay live for "skip", so mute is no longer viable and reference-based echo subtraction is in scope.

## Refusals

- Never wake-word-free. Always-listening-and-guessing is out; the gate stays.
- Never a coding agent. If code work enters scope, it prompts Claude Code — it does not do the work itself.
- Never widens its *surface* past music. The harness underneath stays general; the thing it does stays narrow.
- Never keeps a memory the user cannot read or burn. Diary inspectable, deletable in one command.

## Open creative questions

- How opinionated is "a little bit"? Where is the line between "you always skip this" and nagging?
- Library-only was a *maybe*, not a yes — does it ever reach past Muse for something the user does not own?
- ~~What the box remembers vs what Muse remembers.~~ **Resolved** in the spec (Decision: Diary storage): Muse owns taste — plays, ratings, feedback. The harness owns context — what was asked, what was chosen, why, what was rejected — referencing Muse track IDs rather than copying them.
- Working name. Still unpicked.

## Parked for planning

- Two-model split (fast reply vs tool-calling) on Ollama Cloud free tier; concurrency = 1.
- Host machine must be always-on — rules out mlx (Apple-only); pipeline needs to run on Linux.
- Mic mute window is sized for TTS seconds, not song minutes — voice interrupt during playback unsolved.
- Single I2S audio path, no mixing — music and speech are mutually exclusive on the wire.
- `muse_proxy.py` plays by track id only; search/vibe lives on the Muse API.
- MCP-style tool registration — mechanism undecided.
- Where the diary lives, and what "burn it" actually deletes.
- Which context signals the box passes to Muse.
- Muse recommender architecture — sequence + mood + audio + lyrics context. Second design pass, after the box.
- Coupling risk: box leans on Muse's API; recommender changes can break box assumptions.

## Provenance

Every concept section assembled from user picks: itch (2+4), someone (1+2), heart (2+4), twist (1+4, 2 dialed down, 3 refused), edges (1, 3-soft, 4 + Claude Code delegation note), shape (user's words, verbatim). Scope correction — Muse recommender is same-effort second pass, not a later version — user-issued. Two Should lines flagged as inferred, not user-picked.
