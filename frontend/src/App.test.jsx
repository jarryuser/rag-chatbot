import React, { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReadableStream } from 'node:stream/web'
import App from './App.jsx'
import { ACTIVE_SESSION_KEY, HISTORY_KEY } from './chat.js'

const sessionId = '12e77c34-e04e-4cd0-ab03-242440bb2d09'
const otherId = '14544815-c969-4bb5-987a-e32a00919dca'
const citation = { id: 1, source: 'guide.pdf', page: 2, text: 'Project Aurora launched on 12 March 2025.' }
const encoder = new TextEncoder()
const json = (data, ok = true) => ({ ok, json: async () => data })
const frame = event => encoder.encode(`data: ${JSON.stringify(event)}\n\n`)
let sessions, pending, requests, aborted

function mount() { return render(<StrictMode><App /></StrictMode>) }

beforeEach(() => {
  const saved = new Map()
  vi.stubGlobal('localStorage', {
    getItem: key => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, String(value)),
    clear: () => saved.clear(),
  })
  vi.stubGlobal('FormData', window.FormData)
  vi.stubGlobal('File', window.File)
  localStorage.clear()
  sessions = [{ id: sessionId, name: 'New Chat', documents: [] }]
  pending = false
  aborted = false
  requests = []
  Element.prototype.scrollIntoView = vi.fn()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  vi.stubGlobal('fetch', vi.fn(async (url, options = {}) => {
    requests.push({ url, ...options })
    if (url === '/api/sessions' && !options.method) return json({ sessions: structuredClone(sessions) })
    if (url === '/api/sessions' && options.method === 'POST') return json(sessions[0])
    if (url.startsWith('/api/upload')) {
      const file = options.body.get('file')
      sessions[0].documents.push(file.name)
      return json({ filename: file.name, chunks: 3 })
    }
    if (url.includes('/auto-name')) return json({ ...sessions[0], name: 'Project Aurora' })
    if (url === '/api/chat/stream') {
      return { ok: true, body: new ReadableStream({ start(controller) {
        options.signal.addEventListener('abort', () => {
          aborted = true
          try { controller.error(new DOMException('Stopped', 'AbortError')) } catch { /* Already closed */ }
        })
        controller.enqueue(frame({ type: 'sources', citations: [citation], sources: 'guide.pdf p.2' }))
        controller.enqueue(frame({ type: 'token', content: 'It launched on 12 March 2025 [1].' }))
        if (!pending) {
          controller.enqueue(frame({ type: 'done', citations: [citation], sources: 'guide.pdf p.2' }))
          controller.close()
        }
      } }) }
    }
    throw new Error(`Unexpected request: ${url}`)
  }))
})

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('document chat workflow', () => {
  it('uploads a file, answers, opens the supporting passage, and restores it after remount', async () => {
    const user = userEvent.setup()
    let view = mount()
    await waitFor(() => expect(view.container.querySelector('.chat-title').textContent).toBe('New Chat'))
    await user.upload(view.container.querySelector('input[type="file"]'),
      new File(['synthetic document'], 'guide.pdf', { type: 'application/pdf' }))
    await screen.findByText('✅ Indexed')
    await user.type(view.container.querySelector('textarea'), 'When did Project Aurora launch?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    const reference = await screen.findByRole('link', { name: 'View source 1' })
    await user.click(reference)
    expect(view.container.querySelector('details').open).toBe(true)
    expect(view.container.querySelector('blockquote').textContent).toBe(citation.text)
    expect(view.container.querySelector('summary').textContent).toContain('Page 2')
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Stop response' })).toBeNull())
    fireEvent(window, new window.Event('pagehide'))
    view.unmount()
    view = mount()
    await screen.findByRole('link', { name: 'View source 1' })
    expect(view.container.querySelector('.message.assistant .bubble').textContent).toContain('12 March 2025')
    await user.click(screen.getByRole('link', { name: 'View source 1' }))
    expect(view.container.querySelector('details').open).toBe(true)
    expect(view.container.querySelector('blockquote').textContent).toBe(citation.text)
    expect(requests.filter(request => request.url === '/api/chat/stream')).toHaveLength(1)
  })

  it('stops an active answer, preserves partial content and sources, and permits the next question', async () => {
    pending = true
    const user = userEvent.setup()
    let view = mount()
    await waitFor(() => expect(view.container.querySelector('.chat-title').textContent).toBe('New Chat'))
    let input = view.container.querySelector('textarea')
    await user.type(input, 'Explain the launch')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByRole('link', { name: 'View source 1' })
    expect(input.disabled).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Stop response' }))
    await screen.findByText('Response stopped')
    expect(aborted).toBe(true)
    expect(input.disabled).toBe(false)
    expect(view.container.querySelector('.message.assistant .bubble').textContent).toContain('12 March 2025')
    await user.click(screen.getByRole('link', { name: 'View source 1' }))
    expect(view.container.querySelector('blockquote').textContent).toBe(citation.text)
    fireEvent(window, new window.Event('pagehide'))
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY))
    expect(saved[sessionId].at(-1).stopped).toBe(true)
    view.unmount()
    view = mount()
    await screen.findByText('Response stopped')
    await user.click(screen.getByRole('link', { name: 'View source 1' }))
    expect(view.container.querySelector('blockquote').textContent).toBe(citation.text)
    input = view.container.querySelector('textarea')
    pending = false
    await user.type(input, 'Which project?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Stop response' })).toBeNull())
    const body = JSON.parse(requests.filter(request => request.url === '/api/chat/stream').at(-1).body)
    expect(body.history.every(message => message.role !== 'assistant')).toBe(true)
  })

  it('restores the selected older session, instead of switching to the newest', async () => {
    sessions = [{ id: otherId, name: 'Newer chat', documents: [] }, { id: sessionId, name: 'Older chat', documents: [] }]
    localStorage.setItem(ACTIVE_SESSION_KEY, sessionId)
    localStorage.setItem(HISTORY_KEY, JSON.stringify({ [sessionId]: [{ id: 'saved', role: 'user', content: 'Saved question' }] }))
    const view = mount()
    await screen.findByText('Saved question')
    expect(view.container.querySelector('.chat-title').textContent).toBe('Older chat')
  })

  it('asks before replacement and resends the original file only after confirmation', async () => {
    const originalFetch = fetch
    vi.stubGlobal('fetch', vi.fn((url, options) => {
      if (url.startsWith('/api/upload') && !url.includes('replace=true')) {
        return Promise.resolve({ status: 409, ok: false, json: async () => ({
          detail: { code: 'document_exists', source: 'guide.pdf' },
        }) })
      }
      return originalFetch(url, options)
    }))
    const user = userEvent.setup()
    const view = mount()
    await waitFor(() => expect(view.container.querySelector('.chat-title').textContent).toBe('New Chat'))
    await user.upload(view.container.querySelector('input[type="file"]'), new File(['new'], 'guide.pdf', { type: 'application/pdf' }))
    await screen.findByRole('dialog', { name: 'Replace document?' })
    expect(requests.filter(request => request.url.includes('replace=true'))).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: 'Replace document' }))
    await screen.findByText('✅ Indexed')
    expect(requests.filter(request => request.url.includes('replace=true'))).toHaveLength(1)
  })

  it('keeps the indexed version when replacement is cancelled', async () => {
    const originalFetch = fetch
    vi.stubGlobal('fetch', vi.fn((url, options) => url.startsWith('/api/upload')
      ? Promise.resolve({ status: 409, ok: false, json: async () => ({
        detail: { code: 'document_exists', source: 'guide.pdf' },
      }) }) : originalFetch(url, options)))
    const user = userEvent.setup()
    const view = mount()
    await waitFor(() => expect(view.container.querySelector('.chat-title').textContent).toBe('New Chat'))
    await user.upload(view.container.querySelector('input[type="file"]'), new File(['new'], 'guide.pdf', { type: 'application/pdf' }))
    await screen.findByRole('dialog', { name: 'Replace document?' })
    await user.click(screen.getByRole('button', { name: 'Keep existing' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(fetch.mock.calls.filter(([url]) => url.includes('replace=true'))).toHaveLength(0)
    expect(view.container.querySelectorAll('.doc-item')).toHaveLength(0)
  })

  it('shows a skipped duplicate using its original indexed filename', async () => {
    sessions[0].documents = ['guide.pdf']
    const originalFetch = fetch
    vi.stubGlobal('fetch', vi.fn((url, options) => url.startsWith('/api/upload')
      ? Promise.resolve(json({ filename: 'guide.pdf', chunks: 3, status: 'skipped' }))
      : originalFetch(url, options)))
    const user = userEvent.setup()
    const view = mount()
    await waitFor(() => expect(view.container.querySelector('.chat-title').textContent).toBe('New Chat'))
    await user.upload(view.container.querySelector('input[type="file"]'), new File(['same'], 'renamed.pdf', { type: 'application/pdf' }))
    await screen.findByText('Already indexed')
    expect(view.container.querySelectorAll('.doc-item')).toHaveLength(1)
    expect(view.container.querySelector('.doc-name').textContent).toBe('guide.pdf')
  })

  it('creates only one default session under StrictMode', async () => {
    const originalFetch = fetch
    vi.stubGlobal('fetch', vi.fn((url, options) => url === '/api/sessions' && !options?.method
      ? Promise.resolve(json({ sessions: [] })) : originalFetch(url, options)))
    const view = mount()
    await waitFor(() => expect(view.container.querySelector('.chat-title').textContent).toBe('New Chat'))
    expect(requests.filter(request => request.url === '/api/sessions' && request.method === 'POST')).toHaveLength(1)
  })

  it('clearing an active reply cancels it and does not recreate the removed messages', async () => {
    pending = true
    const user = userEvent.setup()
    const view = mount()
    await waitFor(() => expect(view.container.querySelector('.chat-title').textContent).toBe('New Chat'))
    await user.type(view.container.querySelector('textarea'), 'Explain the launch')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByRole('link', { name: 'View source 1' })
    await user.click(screen.getByRole('button', { name: 'Clear', exact: true }))
    await screen.findByText('Upload a document and start asking questions')
    expect(aborted).toBe(true)
    expect(view.container.querySelectorAll('.message')).toHaveLength(0)
    fireEvent(window, new window.Event('pagehide'))
    expect(JSON.parse(localStorage.getItem(HISTORY_KEY))[sessionId]).toEqual([])
  })
})
