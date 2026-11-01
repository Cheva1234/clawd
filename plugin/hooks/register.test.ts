import { expect, test } from 'claude-code/testing'

// Nothing sits beneath the plugin in a test: each `on` below stands for the engine.
async function boot($: any, on: any) {
  const spawned: string[][] = []
  const posted: any[] = []
  const submitted: any[] = []
  const pendingOut: string[] = []
  let wake: (() => void) | null = null
  let hang = false
  let runOut = '/run/user/1000\nvenv\n' // what the environment check prints: the runtime dir, then 'venv' if the checkout has one
  let spawnFails = false
  const toasts: string[] = []
  on('command.register', () => ({ value: { command: 'clawd' } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('tool.call', () => ({ result: {} }))
  on('session.end', () => ({ sessionId: 's1' }))
  on('classic.Notification', () => ({}))
  on('process.run', () => ({ value: { exitCode: 0, stdout: runOut, stderr: '', isStdoutTruncated: false } }))
  on('ui.toast', (_: any, e: any) => {
    toasts.push(String(e.text ?? e))
    return { value: undefined }
  })
  on('prompt.compose', () => ({ sections: [{ id: 'base', text: 'You are Claude.', scope: 'shared' }] }))
  on('prompt.submit', (_: any, e: any) => {
    submitted.push(e)
    return { text: e.text }
  })
  on('process.spawn', async function* (_: any, e: any) {
    spawned.push([...e.argv])
    if (spawnFails) throw new Error('ENOENT: clawd not found')
    for (;;) {
      // the app runs until it is told to quit; it can print lines to the plugin meanwhile
      while (pendingOut.length) yield { stream: 'stdout', text: pendingOut.shift()! }
      await new Promise<void>(resolve => (wake = resolve))
    }
  })
  on('http.fetch', (_: any, e: any) => {
    posted.push(JSON.parse(e.init.body))
    if (hang) return new Promise(() => {})
    return { value: { ok: true, status: 200, text: 'ok' } }
  })
  await $.session.start({ cwd: '/home/user/work/gigs-api', surface: 'terminal', isInteractive: true })
  const printLine = (text: string) => {
    pendingOut.push(text)
    wake?.()
  }
  return {
    spawned,
    posted,
    submitted,
    toasts,
    printLine,
    setHang: (v: boolean) => (hang = v),
    setRun: (v: string) => (runOut = v),
    setSpawnFails: (v: boolean) => (spawnFails = v),
  }
}

async function settle(until: () => boolean) {
  for (let i = 0; i < 5000 && !until(); i++) await Promise.resolve()
}

test('/clawd opens the app and a second /clawd closes it', async ($, on) => {
  const { spawned, posted } = await boot($, on)
  const first = await $.command.run({ command: 'clawd', args: '' })
  expect(first.text).toMatch(/opened/)
  expect(spawned.length).toBe(1)
  expect(spawned[0].join(' ')).toMatch(/-m clawd --socket \/run\/user\/1000\/clawd\/clawd.sock/)
  const second = await $.command.run({ command: 'clawd', args: '' })
  expect(second.text).toMatch(/closed/)
  expect(posted.at(-1)).toEqual({ kind: 'quit' })
})

test('mute and unmute need an open app, then reach it', async ($, on) => {
  const { posted } = await boot($, on)
  const early = await $.command.run({ command: 'clawd', args: 'mute' })
  expect(early.text).toMatch(/not open/)
  expect(posted.length).toBe(0)
  await $.command.run({ command: 'clawd', args: '' })
  await $.command.run({ command: 'clawd', args: 'mute' })
  await $.command.run({ command: 'clawd', args: 'unmute' })
  expect(posted).toEqual([{ kind: 'mute' }, { kind: 'unmute' }])
})

test('an unknown argument shows the usage and opens nothing', async ($, on) => {
  const { spawned } = await boot($, on)
  const out = await $.command.run({ command: 'clawd', args: 'dance' })
  expect(out.text).toMatch(/Usage/)
  expect(spawned.length).toBe(0)
})

test('a tool call posts tool.call then tool.done, in that order', async ($, on) => {
  const { posted } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  await $.tool.call({ tool: 'Bash', command: 'ls' })
  await settle(() => posted.length >= 2)
  expect(posted).toEqual([
    { kind: 'tool.call', tool: 'Bash', target: 'ls' },
    { kind: 'tool.done', tool: 'Bash' },
  ])
})

test('an edit names the file it works on', async ($, on) => {
  const { posted } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  await $.tool.call({ tool: 'Edit', file_path: '/a/src/gigs.ts', old_string: 'a', new_string: 'b' })
  await settle(() => posted.length >= 2)
  expect(posted[0]).toEqual({ kind: 'tool.call', tool: 'Edit', target: '/a/src/gigs.ts' })
})

test('the app is started with the project folder name', async ($, on) => {
  const { spawned } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  expect(spawned[0].join(' ')).toMatch(/--project gigs-api$/)
})

test('nothing is posted while the app is closed', async ($, on) => {
  const { posted } = await boot($, on)
  await $.tool.call({ tool: 'Bash', command: 'ls' })
  await settle(() => false)
  expect(posted.length).toBe(0)
})

test('a hung app never blocks a tool call', async ($, on) => {
  const { setHang } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  setHang(true)
  const ran = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(ran).toBeDefined() // it came back although the socket never answers
})

test('ending the session closes the app', async ($, on) => {
  const { posted } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  await $.session.end({ reason: 'other' })
  expect(posted.at(-1)).toEqual({ kind: 'quit' })
})

const COMPOSE = {
  model: 'm',
  promptModel: 'm',
  surfaces: ['terminal'],
  tools: [],
  outputStyle: { name: 'default', isKeepingCodingInstructions: true },
  traits: [],
} as any

const line = (text: string) => JSON.stringify({ type: 'submit', text }) + '\n'

test('an approved request from the app is submitted as the user\'s own words', async ($, on) => {
  const { submitted, printLine } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  printLine(line('list the files'))
  await settle(() => submitted.length >= 1)
  expect(submitted.length).toBe(1)
  expect(submitted[0].text).toBe('list the files')
  expect(JSON.stringify(submitted[0])).toMatch(/"asUser":true/)
})

test('a line split across two chunks is still read', async ($, on) => {
  const { submitted, printLine } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  const whole = line('open the readme')
  printLine(whole.slice(0, 12))
  printLine(whole.slice(12))
  await settle(() => submitted.length >= 1)
  expect(submitted.map((s: any) => s.text)).toEqual(['open the readme'])
})

test('an empty request is dropped and a long one is cut to 2000 characters', async ($, on) => {
  const { submitted, printLine } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  printLine(line('   '))
  printLine(line('x'.repeat(5000)))
  await settle(() => submitted.length >= 1)
  expect(submitted.length).toBe(1)
  expect(submitted[0].text.length).toBe(2000)
})

test('while Claude waits on a permission prompt a request is dropped and the app is told', async ($, on) => {
  const { submitted, posted, printLine } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  await $.classic.Notification({ notification_type: 'permission_prompt', message: 'Claude needs your permission' })
  printLine(line('delete everything'))
  await settle(() => posted.some((p: any) => p.kind === 'notice'))
  expect(submitted.length).toBe(0)
  expect(posted.find((p: any) => p.kind === 'notice').text).toMatch(/waiting for you/)
})

test('once the prompt is answered requests go through again', async ($, on) => {
  const { submitted, printLine } = await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  await $.classic.Notification({ notification_type: 'permission_prompt', message: 'x' })
  await $.tool.call({ tool: 'Bash', command: 'ls' }) // the call finishes: the prompt was answered
  printLine(line('list the files'))
  await settle(() => submitted.length >= 1)
  expect(submitted.map((s: any) => s.text)).toEqual(['list the files'])
})

test('while Clawd is open, Claude is told that plugin messages are the user speaking and that replies are read aloud', async ($, on) => {
  await boot($, on)
  const before = (await $.prompt.compose(COMPOSE)).sections.map((s: any) => s.id)
  expect(before).toEqual(['base'])
  await $.command.run({ command: 'clawd', args: '' })
  const sections = (await $.prompt.compose(COMPOSE)).sections
  expect(sections.map((s: any) => s.id)).toEqual(['base', 'clawd-voice'])
  const note = sections[1].text
  expect(note).toMatch(/clawd plugin/i)
  expect(note).toMatch(/speech-to-text/i)
  expect(note).toMatch(/aloud/i)
  expect(note).toMatch(/never mention/i) // answer as in a spoken conversation, not about the transcript
  expect(note).toMatch(/transcript/i)
  expect(note).not.toMatch(/do not say you cannot hear/i)
  expect(sections[1].scope).toBe('session')
})

test('after Clawd closes, the voice note is gone', async ($, on) => {
  await boot($, on)
  await $.command.run({ command: 'clawd', args: '' })
  await $.command.run({ command: 'clawd', args: '' })
  expect((await $.prompt.compose(COMPOSE)).sections.map((s: any) => s.id)).toEqual(['base'])
})


test('without a checkout venv the app is started from the clawd command on the PATH', async ($, on) => {
  const { spawned, setRun } = await boot($, on)
  setRun('/run/user/1000\n') // no 'venv' line: installed with pipx, there is no checkout next to the plugin
  const out = await $.command.run({ command: 'clawd', args: '' })
  expect(out.text).toMatch(/opened/)
  expect(spawned[0][0]).toBe('clawd')
  expect(spawned[0].join(' ')).toMatch(/--socket \/run\/user\/1000\/clawd\/clawd.sock --project gigs-api$/)
})

test('the socket lives in the user runtime directory, whatever it is', async ($, on) => {
  const { spawned, setRun } = await boot($, on)
  setRun('/run/user/4242\nvenv\n')
  await $.command.run({ command: 'clawd', args: '' })
  expect(spawned[0].join(' ')).toMatch(/--socket \/run\/user\/4242\/clawd\/clawd.sock/)
})

test('without a runtime directory nothing is started and the user is told why', async ($, on) => {
  const { spawned, setRun } = await boot($, on)
  setRun('\n')
  const out = await $.command.run({ command: 'clawd', args: '' })
  expect(out.text).toMatch(/XDG_RUNTIME_DIR/)
  expect(spawned.length).toBe(0)
  const later = await $.command.run({ command: 'clawd', args: 'mute' })
  expect(later.text).toMatch(/not open/)
})

test('if the app cannot be started the user is told how to install it', async ($, on) => {
  const { toasts, setRun, setSpawnFails } = await boot($, on)
  setRun('/run/user/1000\n')
  setSpawnFails(true)
  await $.command.run({ command: 'clawd', args: '' })
  await settle(() => toasts.length >= 1)
  expect(toasts[0]).toMatch(/pipx install/)
})
