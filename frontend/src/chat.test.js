import test from 'node:test'
import assert from 'node:assert/strict'
import { loadHistory, saveHistory, updateMessage, readEvents, HISTORY_KEY } from './chat.js'
import { remarkCitations } from './citations.js'

const session = 'a3a38f4a-adf4-4ee0-8410-4235438ce494'
const storage = () => {
  const values = new Map()
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
}

test('history survives reload and interrupted replies are no longer streaming', () => {
  const saved = storage()
  saveHistory(saved, { [session]: [{ id: '1', role: 'assistant', content: 'Partial', streaming: true }] })
  const messages = loadHistory(saved)[session]
  assert.equal(messages[0].content, 'Partial')
  assert.equal(messages[0].streaming, false)
  assert.equal(messages[0].stopped, true)
})

test('clearing or deleting a conversation persists', () => {
  const saved = storage()
  saveHistory(saved, { [session]: [] })
  assert.deepEqual(loadHistory(saved), { [session]: [] })
  saveHistory(saved, {})
  assert.deepEqual(loadHistory(saved), {})
})

test('storage bounds history to the most recent 200 messages', () => {
  const saved = storage()
  saveHistory(saved, { [session]: Array.from({ length: 210 }, (_, i) =>
    ({ id: `${i}`, role: 'user', content: `${i}` })) })
  assert.equal(loadHistory(saved)[session].length, 200)
  assert.equal(loadHistory(saved)[session][0].content, '10')
})

test('invalid stored entries are ignored', () => {
  const saved = storage()
  saved.setItem(HISTORY_KEY, JSON.stringify({ [session]: [null, { role: 'system', content: 'x' }], bad: [] }))
  assert.deepEqual(loadHistory(saved), { [session]: [] })
})

test('tokens update their message even when another message was appended', () => {
  const before = { [session]: [
    { id: 'answer', content: 'Hello' }, { id: 'next', content: 'New question' },
  ] }
  const after = updateMessage(before, session, 'answer', m => ({ ...m, content: m.content + '!' }))
  assert.equal(after[session][0].content, 'Hello!')
  assert.equal(after[session][1].content, 'New question')
  assert.equal(before[session][0].content, 'Hello')
  assert.deepEqual(updateMessage({}, session, 'answer', () => assert.fail()), {})
})

test('SSE parsing handles split UTF-8 bytes, CRLF, and a final event without a separator', async () => {
  const bytes = new TextEncoder().encode(': heartbeat\r\n\r\ndata: {"type":"token","content":"Привет"}\r\n\r\ndata: {"type":"done"}')
  const body = new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
    controller.close()
  } })
  const events = []
  for await (const event of readEvents(body)) events.push(event)
  assert.deepEqual(events, [{ type: 'token', content: 'Привет' }, { type: 'done' }])
})

test('leaving the event loop cancels the network reader', async () => {
  let cancelled = false
  const body = new ReadableStream({
    start(controller) { controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n')) },
    cancel() { cancelled = true },
  })
  for await (const event of readEvents(body)) { assert.equal(event.type, 'done'); break }
  assert.equal(cancelled, true)
  assert.equal(body.locked, false)
})

test('malformed SSE is reported and releases the reader', async () => {
  const body = new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode('data: invalid\n\n'))
    controller.close()
  } })
  await assert.rejects(async () => { for await (const event of readEvents(body)) void event })
  assert.equal(body.locked, false)
})


test('citation links use only supplied reference IDs and leave code and existing links unchanged', () => {
  const tree = { type: 'root', children: [
    { type: 'paragraph', children: [{ type: 'text', value: 'Fact [1], unsupported [9].' }] },
    { type: 'code', value: '[1]' },
    { type: 'paragraph', children: [
      { type: 'inlineCode', value: '[1]' },
      { type: 'link', url: 'https://example.com', children: [{ type: 'text', value: '[1]' }] },
    ] },
  ] }
  remarkCitations({ ids: [1] })(tree)
  assert.equal(tree.children[0].children[1].url, '#source-1')
  assert.equal(tree.children[0].children[2].value, ', unsupported [9].')
  assert.equal(tree.children[1].value, '[1]')
  assert.equal(tree.children[2].children[0].type, 'inlineCode')
  assert.equal(tree.children[2].children[1].children[0].type, 'text')
})
