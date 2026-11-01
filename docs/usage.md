# Clawd: how to use it

## Start and stop
- In a Claude Code session started with the plugin: `claude --plugin-dir ./plugin`
- `/clawd` opens the floating Clawd and **the call is live right away** (a second `/clawd`, or `/clawd off`, closes it).
- **Click Clawd to mute or unmute** (also the **mute** button, or `/clawd mute` / `/clawd unmute`). Muted = hung up: the mic is closed and nothing is sent to ElevenLabs. The tag in the bubble says `● LIVE` or `MUTED`.
- Clawd closes when the session ends or its window (the **×** button) is closed.

## The call
- While unmuted you just talk. A small detector on this machine hears when someone is speaking; **only speech is sent to ElevenLabs, never silence**. Your words appear in the bubble as you speak; filler words ("uh") and false starts are removed.
- When you stop (about a second), a **1.5 s countdown** shows what will be sent. **Send** sends now, **Cancel** drops it, clicking the text edits it. If you keep talking during the countdown, the new words join the same request.
- The text goes into the session as if you typed it. If Claude is busy it is queued behind the current turn.
- **Talk over Clawd and it stops speaking** at once. Claude's work is not interrupted.
- **After 2 minutes of silence** (nobody speaking, Clawd not speaking) the call mutes itself and shows a notice. Three failed listening tries in a row (no network, key rejected) also mute it.
- Not allowed while Claude waits for you to answer a permission prompt: Clawd ignores speech then and says so.
- While Clawd is open, Claude is told (in its system prompt, invisible to you) that messages shown as "Prompt from the clawd plugin" are you speaking through speech-to-text, and that its replies are read aloud, so it starts with a short speakable answer.
- Assumes headphones. With speakers, Clawd could hear itself and cut itself off.

## What Clawd says back
- After a reply Clawd **shows and speaks Claude's own words**, word for word (markdown and code removed). Up to about 300 characters whole; for a longer reply, the first whole sentences, then "The full answer is in the terminal." No model rewrites it, so it matches the terminal.
- Nothing is spoken while muted or closed.

## What the bubble shows
Status badge (IDLE, LISTENING, THINKING, WORKING, NEEDS YOU, SPEAKING, DONE, FAILED), a ticker of the current action, the text above, `actions · files changed · time`, and your Claude usage limits (`Claude 5h 34% · week 82% · resets Mon 1 pm`: yellow from 80%, red from 95%; shown only for accounts that have limits). Right-click Clawd to hide or show the bubble; drag to move it.

## Settings (optional): `~/.config/cheva-clawd/config.json`
```json
{ "voice_id": "JBFqnCBsd6RMkjVDRZzb", "model_id": "eleven_flash_v2_5",
  "daily_chars": 8000, "daily_listen_seconds": 1800, "countdown_secs": 1.5 }
```
- The ElevenLabs key lives only in `~/.config/cheva-clawd/secrets/elevenlabs.key` (mode 0600). It is never printed or logged.

## What costs something (ElevenLabs only)
- Speech: characters spoken, capped per day (`daily_chars`). Listening: seconds of actual speech, capped per day (`daily_listen_seconds`). Usage files: `voice-usage.json`, `listen-usage.json` in the same folder.
- No Claude usage is spent by Clawd (the summary model is gone).

## Files
- App: `clawd/` (Python, Qt). Plugin: `plugin/`. Tests: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q` and `claude plugin test plugin`.
- How it works: `docs/how-it-works.md`.
