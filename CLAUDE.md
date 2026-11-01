# Clawd

A floating pixel pet for Claude Code (`/clawd`) with a voice call. See `README.md` and `docs/how-it-works.md`.

## Run the tests
- App: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`
- Plugin: `claude plugin test plugin` (and `claude plugin validate plugin`)

## Rules for changes
- The ElevenLabs key lives only in `~/.config/cheva-clawd/secrets/elevenlabs.key` (mode 0600). Never print it, put it on a command line, log it or commit it.
- No ElevenLabs call and no speech while the widget is closed or muted.
- Write the failing test first. Real checks against the real services find bugs that fakes hide.
- Add files by explicit path.
