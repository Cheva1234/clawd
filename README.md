# Clawd

A small pixel pet that floats on your desktop while you use [Claude Code](https://claude.com/claude-code), shows what Claude is doing, and lets you **talk to it like a phone call**.

> **Unofficial fan project.** Clawd is the Claude Code mascot and belongs to Anthropic. This project is not affiliated with, endorsed by, or sponsored by Anthropic or ElevenLabs.

## What it does
- **Shows the session.** A speech bubble over the pet: a status badge (idle, thinking, working, needs you, done, failed), a live ticker of the current action (`EDITS gigs.ts`, `RUNS npm test`), and `actions · files changed · time`.
- **Speaks Claude's own words.** After a reply it shows and speaks the reply itself, word for word: up to about 300 characters whole, otherwise the first whole sentences and "The full answer is in the terminal." No model rewrites it, so it always matches the terminal.
- **A real-time call.** While unmuted the mic is live and you just talk. A small local detector decides when you are speaking, so only speech is sent for transcription. When you pause you get a short countdown (1.5 s) with Cancel, then your words go into the session as if you typed them. Talk over Clawd and it stops speaking. After 2 minutes of silence the call mutes itself.
- **Safe by default.** Nothing is sent to Claude without the countdown. While Claude waits for you to answer a permission prompt, speech is ignored.

## Requirements
- Linux with a systemd login session (`XDG_RUNTIME_DIR`), PipeWire or PulseAudio, and X11 or XWayland (on Wayland the app runs through XWayland so it can stay on top). Developed and tested on KDE Plasma (Wayland). macOS and Windows are untested.
- Python 3.12 or newer, and [Claude Code](https://claude.com/claude-code).
- An [ElevenLabs](https://elevenlabs.io) API key (text-to-speech and speech-to-text).
- Headphones are recommended: through speakers Clawd can hear itself.

## Install
1. Install the app:
   ```bash
   pipx install git+https://github.com/Cheva1234/clawd
   ```
2. Put your ElevenLabs key in a private file (the app refuses a file other users can read, and never prints the key):
   ```bash
   ( umask 077; mkdir -p ~/.config/cheva-clawd/secrets
     read -rsp "ElevenLabs API key: " k; echo
     printf '%s\n' "$k" > ~/.config/cheva-clawd/secrets/elevenlabs.key )
   ```
3. In Claude Code, install the plugin:
   ```
   /plugin install clawd --marketplace Cheva1234/clawd
   ```
4. Type `/clawd`. The pet appears and the call is live. Click it to mute or unmute. `/clawd` again closes it.

### From a source checkout
```bash
git clone https://github.com/Cheva1234/clawd && cd clawd
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
claude --plugin-dir ./plugin
```
The plugin uses the checkout's `.venv` when there is one, otherwise the `clawd` command on your PATH.

## Using it
See [docs/usage.md](docs/usage.md). In short: unmuted = live call; click Clawd to mute; Send / Cancel / edit during the countdown; right-click Clawd to hide the bubble; drag to move it.

## Settings
Optional, in `~/.config/cheva-clawd/config.json`:
```json
{ "voice_id": "JBFqnCBsd6RMkjVDRZzb", "model_id": "eleven_flash_v2_5",
  "daily_chars": 8000, "daily_listen_seconds": 1800, "countdown_secs": 1.5 }
```
`voice_id` is any ElevenLabs voice available to your account. The two daily caps limit how many characters Clawd speaks and how many seconds of speech it listens to per day.

## Privacy and cost
- While unmuted, the microphone is open on your machine. **Only audio of speech is sent to ElevenLabs** (never silence), and only for as long as you speak. Muted = the mic is closed and nothing is sent.
- The first ~300 characters of each of Claude's replies are sent to ElevenLabs to be spoken. Nothing else leaves your machine; there is no telemetry.
- Both uses cost ElevenLabs credits. The daily caps above bound them.
- While Clawd is open, the plugin adds a short note to Claude's system prompt: messages that arrive from the Clawd plugin are your speech, and replies are read aloud.

## How it works
See [docs/how-it-works.md](docs/how-it-works.md).

## Development
```bash
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q     # the app
claude plugin test plugin                           # the plugin
```

## License
MIT. See [LICENSE](LICENSE).
