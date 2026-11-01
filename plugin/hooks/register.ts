// Clawd plugin: /clawd opens the floating pet; session events drive its animations.
import type { Register } from 'claude-code'

const USAGE = 'Usage: /clawd (open or close), /clawd mute, /clawd unmute, /clawd off'
const INSTALL_HINT = 'Install the app with: pipx install git+https://github.com/Cheva1234/clawd'

let sock = '' // the Unix socket the app listens on, in the user's runtime directory
let running = false
let project = ''
let waiting = false // a permission prompt is open: nothing may be typed into the session
let outBuf = '' // the app's stdout arrives in chunks, not lines
// Events go out in order, never blocking the session: a hung app must not stall a tool call.
let queue: Promise<void> = Promise.resolve()

// What Claude is told while Clawd is open: messages from the clawd plugin are the user's speech.
const VOICE_NOTE =
  'The Clawd desktop pet is open in this session and the user may be talking to you by voice. ' +
  'A message shown as "Prompt from the clawd plugin" is the user speaking, delivered to you as text: ' +
  'read it as speech and interpret it by meaning, since it may contain small errors. ' +
  'Treat it as a normal spoken conversation and respond to what was said: never mention transcripts, transcription, speech-to-text, ' +
  'audio, microphones, or how the message reached you. ' +
  'Clawd shows your reply in a small bubble and reads it aloud (roughly the first 300 characters): ' +
  'start with a short, plain, speakable answer in one or two sentences, with no markdown or code in that part, then add detail after it if needed.'

// What a tool call works on, as one short string for the panel's ticker.
function targetOf(e: any): string {
  const t = e.file_path ?? e.notebook_path ?? e.command ?? e.pattern ?? e.url ?? e.query ?? e.path ?? ''
  return String(t).slice(0, 300)
}

async function send($: any, ev: Record<string, unknown>) {
  try {
    await $.http.fetch('http://clawd/event', {
      method: 'POST',
      body: JSON.stringify(ev),
      socketPath: sock,
    })
  } catch {
    // the app is starting or closing: the pet is a nicety, never an error
  }
}

function post($: any, ev: Record<string, unknown>) {
  if (!running) return
  queue = queue.then(() => send($, ev))
}

// Claude's usage limits (the 5-hour and weekly windows) for the bubble. An account without them sends an empty list.
function toLimits(windows: any): Record<string, unknown>[] {
  return (Array.isArray(windows) ? windows : []).map((w: any) => ({
    kind: w.kind,
    percentUsed: w.percentUsed,
    resetsAt: w.resetsAt,
  }))
}

async function usageSoon($: any) {
  try {
    await $.clock.sleep(2000) // the app needs a moment before it listens on the socket
    const usage = await $.session.usage()
    post($, { kind: 'usage', limits: toLimits(usage.rateLimits) })
  } catch {
    // aborted by a reload or the end of the session, or no usage figures: nothing to show
  }
}

async function closeApp($: any) {
  await send($, { kind: 'quit' })
  running = false
}

// A request the user approved in the app. It becomes a prompt in their own words,
// unless Claude is waiting for a permission answer: then it is dropped and the app is told.
async function submitText($: any, raw: unknown) {
  const text = String(raw ?? '').trim().slice(0, 2000)
  if (!text) return
  if (waiting) {
    post($, { kind: 'notice', text: 'VOICE: not sent, Claude is waiting for you' })
    return
  }
  await $.prompt.submit({ text, asUser: true })
}

async function readLine($: any, line: string) {
  if (!line.trim()) return
  let msg: any
  try {
    msg = JSON.parse(line)
  } catch {
    return
  }
  if (msg.type === 'closed') running = false
  else if (msg.type === 'submit') await submitText($, msg.text)
}

// Where the app lives and how to start it, without any path fixed to one machine: the socket goes in the
// user's runtime directory; a source checkout next to this plugin (with its .venv) is used if there is
// one, otherwise the `clawd` command on the PATH (pipx install).
async function resolveLaunch($: any): Promise<{ argv: string[]; cwd?: string } | string> {
  const repo = String($.plugin.root ?? '').replace(/\/plugin\/?$/, '')
  const venvPython = `${repo}/.venv/bin/python`
  let stdout = ''
  try {
    const res = await $.process.run([
      'sh',
      '-c',
      'printf "%s\\n" "${XDG_RUNTIME_DIR:-}"; [ -x "$1" ] && echo venv',
      'sh',
      venvPython,
    ])
    stdout = String(res.stdout ?? '')
  } catch {
    return 'Clawd could not check its environment.'
  }
  const [runtime, venv] = stdout.split('\n')
  if (!runtime) return 'Clawd needs the XDG_RUNTIME_DIR environment variable (a systemd Linux login session).'
  sock = `${runtime}/clawd/clawd.sock`
  const args = ['--socket', sock, '--project', project]
  return venv === 'venv' ? { argv: [venvPython, '-m', 'clawd', ...args], cwd: repo } : { argv: ['clawd', ...args] }
}

async function watchApp($: any, launch: { argv: string[]; cwd?: string }) {
  try {
    for await (const { stream, text } of $.process.spawn({
      argv: launch.argv,
      ...(launch.cwd ? { cwd: launch.cwd } : {}),
    })) {
      if (stream !== 'stdout') continue
      outBuf += text
      const lines = outBuf.split('\n')
      outBuf = lines.pop() ?? ''
      for (const line of lines) await readLine($, line)
    }
  } catch (err) {
    await $.ui.toast(`Clawd could not start (${String(err)}). ${INSTALL_HINT}`)
  } finally {
    running = false
    outBuf = ''
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    project = String(e.cwd ?? '').split('/').filter(Boolean).pop() ?? ''
    await $.command.register({
      name: 'clawd',
      description: 'Open or close the floating Clawd pet',
      argumentHint: '[mute|unmute|off]',
    })
    return next(e)
  })

  on('command.run', { command: 'clawd' }, async ($, e) => {
    const arg = (e.args ?? '').trim()
    if (arg === 'mute' || arg === 'unmute') {
      if (!running) return { text: 'Clawd is not open. Type /clawd first.' }
      await send($, { kind: arg })
      return { text: arg === 'mute' ? 'Clawd muted.' : 'Clawd unmuted.' }
    }
    if (arg === 'off' || (arg === '' && running)) {
      if (!running) return { text: 'Clawd is not open.' }
      await closeApp($)
      return { text: 'Clawd closed.' }
    }
    if (arg !== '') return { text: USAGE }
    const launch = await resolveLaunch($)
    if (typeof launch === 'string') return { text: launch }
    running = true
    void watchApp($, launch)
    void usageSoon($)
    return { text: 'Clawd opened. /clawd again closes it.' }
  })

  // While Clawd is open Claude is told how the user is talking to it and what happens to its replies.
  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    if (!running) return composed
    return { sections: [...composed.sections, { id: 'clawd-voice', text: VOICE_NOTE, scope: 'session' as const }] }
  })

  on('session.measure', async ($, e, next) => {
    post($, { kind: 'usage', limits: toLimits(e.rateLimits) })
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    waiting = false
    post($, { kind: 'turn.start' })
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    post($, { kind: 'tool.call', tool: e.tool, target: targetOf(e) })
    const ran = await next(e)
    waiting = false // the call finished, so any prompt it raised was answered
    post($, { kind: 'tool.done', tool: e.tool })
    return ran
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    waiting = false
    post($, { kind: 'turn.complete', reason: e.reason, text: String(done?.text ?? '').slice(0, 4000) })
    return done
  })

  on('classic.PermissionRequest', async ($, e, next) => {
    post($, { kind: 'permission', tool: e.tool_name })
    return next(e)
  })

  on('classic.Notification', async ($, e, next) => {
    if (e.notification_type === 'permission_prompt') waiting = true
    post($, { kind: 'notification', type: e.notification_type })
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    if (running) await closeApp($)
    return next(e)
  })
}
