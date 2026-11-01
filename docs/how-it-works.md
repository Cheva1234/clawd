# How Clawd works

Two parts that talk over a local socket.

```
 Claude Code session                                  Clawd app (Python, Qt)
 ┌──────────────────────┐   events (HTTP over a        ┌────────────────────────────────┐
 │ plugin (TypeScript)  │   Unix socket in your   ───► │ controller → view → bubble     │
 │  /clawd, hooks       │   runtime directory)         │ sprite animations              │
 │                      │                              │                                │
 │  $.prompt.submit  ◄──┼── JSON lines on stdout ◄──── │ call: mic → detector → STT     │
 └──────────────────────┘                              │       countdown → submit       │
                                                       │ voice: reply text → TTS        │
                                                       └────────────────────────────────┘
```

## The plugin (`plugin/`)
A Claude Code plugin written with the plugin (mod) API.
- `/clawd` starts the app as a child process (`$.process.spawn`): from the checkout's `.venv` if there is one, otherwise the `clawd` command on your PATH. The socket is `$XDG_RUNTIME_DIR/clawd/clawd.sock` in a private (0700) directory.
- Session events (turn start/end, tool calls with what they work on, permission prompts) are posted to the app in order and never block the session.
- When you approve a spoken request, the app prints one JSON line; the plugin submits it with `$.prompt.submit({ text, asUser: true })`. It drops the request if a permission prompt is open.
- While Clawd is open, a system-prompt section tells Claude that messages from the plugin are your speech and that replies are read aloud.

## The app (`clawd/`)
- `state.py`, `session.py`, `view.py`, `format.py`, `controller.py`: events → animation state → what the bubble shows (all plain logic, unit tested).
- `window.py`, `sprites.py`: the frameless, transparent, always-on-top window, the stepped-corner bubble, the pixel sprite and its animations.
- `call.py`: the phone call. One continuous mic (`audio.QtMicIn`) feeds `gate.SpeechGate`, a small local energy-based speech detector (adaptive background, preroll, forced end). Each stretch of speech opens one `stt.Listener` session (ElevenLabs Scribe realtime over a WebSocket, manual commit). The final text counts down (`confirm.PendingRequest`) and is then submitted. More speech during the countdown joins the same request; speech while Claude waits on a permission prompt is ignored; three failed sessions in a row, or 2 minutes of silence, mute the call.
- `voice.py`, `tts.py`: after a reply, `format.spoken_text` picks the reply's own words and `tts.Speaker` streams ElevenLabs speech to the speakers. Talking over Clawd stops it (barge-in).
- `keys.py`, `credits.py`, `config.py`: the key (a 0600 file, never printed), daily caps, settings.

## Design choices worth knowing
- **No summary model.** An earlier version rewrote Claude's reply with a small model and once flipped its meaning, so Clawd now only quotes the reply.
- **Manual commit.** The local detector decides when a sentence ends and commits by hand; the server's own silence timeout would never fire after the stream stops.
- **Noisy rooms.** The detector learns the background from the quietest fifth of the last 2 seconds, and judges the end of speech on a smoothed level, because a loud mic background once kept it stuck on "speaking".
