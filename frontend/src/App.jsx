import { useState, useCallback, useEffect, useRef } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ChatWindow from './components/ChatWindow.jsx'

import { loadHistory, saveHistory, updateMessage, readEvents, normalizeCitations, restoreSession, ACTIVE_SESSION_KEY } from './chat.js'

const API = ''

export default function App() {
  // All sessions: [{ id, name, created_at, documents[] }]
  const [sessions, setSessions] = useState([])
  // ID of the currently open session
  const [currentSessionId, setCurrentSessionId] = useState(null)
  // Per-session chat history: { [sessionId]: [{ role, content, sources? }] }
  const [storageError, setStorageError] = useState('')
  const [apiError, setApiError] = useState('')
  const [chatHistory, setChatHistory] = useState(() => {
    try { return loadHistory(localStorage) } catch { return {} }
  })
  const activeRequest = useRef(null)
  const initialLoad = useRef(null)
  const historyRef = useRef(chatHistory)
  historyRef.current = chatHistory

  useEffect(() => {
    const persist = () => {
      try {
        saveHistory(localStorage, historyRef.current)
        setStorageError('')
      } catch {
        setStorageError('Chat history could not be saved in this browser. Copy important messages before closing.')
      }
    }
    const timer = setTimeout(persist, 300)
    window.addEventListener('pagehide', persist)
    return () => {
      clearTimeout(timer)
      window.removeEventListener('pagehide', persist)
    }
  }, [chatHistory])

  useEffect(() => () => activeRequest.current?.controller.abort(), [])

  useEffect(() => {
    if (currentSessionId) {
      try { localStorage.setItem(ACTIVE_SESSION_KEY, currentSessionId) } catch { /* History notice handles storage errors */ }
    }
  }, [currentSessionId])

  const [isLoading, setIsLoading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState(null)
  const [urlIngestStatus, setUrlIngestStatus] = useState(null)

  // Current session object derived from state
  const currentSession = sessions.find(s => s.id === currentSessionId) ?? null

  // ── Load sessions on mount, auto-create default if none ──────────────────
  useEffect(() => {
    if (!initialLoad.current) initialLoad.current = fetch(`${API}/api/sessions`)
      .then(r => { if (!r.ok) throw new Error('Could not load chats'); return r.json() })
      .then(async data => {
        let list = data.sessions ?? []
        if (list.length === 0) {
          // First launch — create a default session automatically
          const res = await fetch(`${API}/api/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: 'New Chat' }),
          })
          if (!res.ok) throw new Error('Could not create a chat')
          const session = await res.json()
          list = [session]
        }
        return list
      })
    let cancelled = false
    initialLoad.current.then(list => {
      if (cancelled) return
      setSessions(list)
      setCurrentSessionId(restoreSession(localStorage, list))
      setChatHistory(prev => Object.fromEntries(Object.entries(prev)
        .filter(([id]) => list.some(session => session.id === id))))
    }).catch(() => {
      if (!cancelled) setApiError('Could not load chats. Please reload the page.')
    })
    return () => { cancelled = true }
  }, [])

  // ── Session handlers ──────────────────────────────────────────────────────
  const handleCreateSession = useCallback(async () => {
    const res = await fetch(`${API}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New Chat' }),
    })
    if (!res.ok) { setApiError('Could not create the chat. Please try again.'); return }
    const session = await res.json()
    setSessions(prev => [session, ...prev])
    setCurrentSessionId(session.id)
  }, [])

  const handleRenameSession = useCallback(async (id, name) => {
    const res = await fetch(`${API}/api/sessions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (!res.ok) { setApiError('Could not rename the chat. Please try again.'); return }
    const updated = await res.json()
    setSessions(prev => prev.map(s => s.id === id ? updated : s))
  }, [])

  const handleDeleteSession = useCallback(async (id) => {
    const res = await fetch(`${API}/api/sessions/${id}`, { method: 'DELETE' })
    if (!res.ok) { setApiError('Could not delete the chat. Please try again.'); return }
    if (activeRequest.current?.sessionId === id) activeRequest.current.controller.abort()
    const data = await res.json()
    const remaining = data.sessions ?? []
    setSessions(remaining)
    // Remove chat history for this session
    setChatHistory(prev => { const n = { ...prev }; delete n[id]; return n })
    // Switch to another session or create a new one
    if (remaining.length === 0) {
      const r = await fetch(`${API}/api/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'New Chat' }),
      })
      if (!r.ok) { setCurrentSessionId(null); setApiError('Could not create a replacement chat.'); return }
      const session = await r.json()
      setSessions([session])
      setCurrentSessionId(session.id)
    } else {
      setCurrentSessionId(remaining[0].id)
    }
  }, [])

  const handleSelectSession = useCallback((id) => {
    setCurrentSessionId(id)
  }, [])

  // ── Upload handler ────────────────────────────────────────────────────────
  const handleUpload = useCallback(async (file) => {
    if (!currentSessionId || !file) return
    setApiError('')
    setUploadStatus('uploading')
    const form = new FormData()
    form.append('file', file)

    try {
      const res = await fetch(
        `${API}/api/upload?session_id=${currentSessionId}`,
        { method: 'POST', body: form }
      )
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Upload failed')

      // Update the document list inside the current session
      setSessions(prev => prev.map(s =>
        s.id === currentSessionId
          ? { ...s, documents: s.documents.includes(data.filename) ? s.documents : [...s.documents, data.filename] }
          : s
      ))
      setUploadStatus('success')
      setTimeout(() => setUploadStatus(null), 3000)
    } catch (err) {
      setApiError(err.message || 'Upload failed')
      setUploadStatus('error')
      console.error(err)
      setTimeout(() => setUploadStatus(null), 4000)
    }
  }, [currentSessionId])

  // ── Ingest URL handler ────────────────────────────────────────────────────
  const handleIngestUrl = useCallback(async (url) => {
    if (!currentSessionId || !url.trim()) return
    setApiError('')
    setUrlIngestStatus('loading')
    try {
      const res = await fetch(
        `${API}/api/ingest-url?session_id=${currentSessionId}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: url.trim() }),
        }
      )
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Ingest failed')

      setSessions(prev => prev.map(s =>
        s.id === currentSessionId
          ? {
              ...s,
              documents: s.documents.includes(data.display_name)
                ? s.documents
                : [...s.documents, data.display_name],
            }
          : s
      ))
      setUrlIngestStatus('success')
      setTimeout(() => setUrlIngestStatus(null), 3000)
    } catch (err) {
      setApiError(err.message || 'URL import failed')
      setUrlIngestStatus('error')
      console.error(err)
      setTimeout(() => setUrlIngestStatus(null), 4000)
    }
  }, [currentSessionId])

  // ── Delete document handler ───────────────────────────────────────────────
  const handleDelete = useCallback(async (filename) => {
    if (!currentSessionId) return
    try {
      const res = await fetch(
        `${API}/api/documents/${encodeURIComponent(filename)}?session_id=${currentSessionId}`,
        { method: 'DELETE' }
      )
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Delete failed')
      setSessions(prev => prev.map(s =>
        s.id === currentSessionId ? { ...s, documents: data.documents ?? [] } : s
      ))
    } catch (err) {
      setApiError(err.message || 'Delete failed')
      console.error('Delete failed:', err)
    }
  }, [currentSessionId])

  // ── Clear conversation handler ────────────────────────────────────────────
  const handleClearChat = useCallback(() => {
    if (activeRequest.current?.sessionId === currentSessionId) activeRequest.current.controller.abort()
    setChatHistory(prev => ({ ...prev, [currentSessionId]: [] }))
  }, [currentSessionId])

  const handleStop = useCallback(() => activeRequest.current?.controller.abort(), [])

  const handleSend = useCallback(async (question) => {
    if (!question.trim() || activeRequest.current || !currentSessionId) return
    const sessionId = currentSessionId
    const priorMessages = (chatHistory[sessionId] ?? [])
      .filter(message => !message.isError && !message.streaming && !message.stopped)
      .slice(-10).map(({ role, content }) => ({ role, content }))
    const isFirstMessage = priorMessages.length === 0 &&
      sessions.find(session => session.id === sessionId)?.name === 'New Chat'
    const messageId = crypto.randomUUID()
    const controller = new AbortController()
    activeRequest.current = { controller, sessionId }
    setIsLoading(true)
    setChatHistory(prev => ({ ...prev, [sessionId]: [
      ...(prev[sessionId] ?? []),
      { id: crypto.randomUUID(), role: 'user', content: question },
      { id: messageId, role: 'assistant', content: '', streaming: true },
    ] }))
    const update = change => setChatHistory(prev => updateMessage(prev, sessionId, messageId, change))

    try {
      const res = await fetch(`${API}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, session_id: sessionId, history: priorMessages }),
        signal: controller.signal,
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Request failed')
      }
      let completed = false
      for await (const event of readEvents(res.body)) {
        if (controller.signal.aborted) throw new DOMException('Stopped', 'AbortError')
        if (event.type === 'sources') {
          update(message => ({ ...message, sources: event.sources, citations: normalizeCitations(event.citations) }))
        } else if (event.type === 'token') {
          update(message => ({ ...message, content: message.content + event.content }))
        } else if (event.type === 'done') {
          completed = true
          update(message => ({ ...message, sources: event.sources,
            citations: event.citations ? normalizeCitations(event.citations) : message.citations, streaming: false }))
          break
        } else if (event.type === 'error') {
          throw new Error(event.detail)
        }
      }
      if (!completed) throw new Error('The connection closed before the answer was complete. Please try again.')
      if (isFirstMessage && !controller.signal.aborted) {
        fetch(`${API}/api/sessions/${sessionId}/auto-name`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question }),
        }).then(r => r.ok ? r.json() : null).then(updated => {
          if (updated) setSessions(prev => prev.map(s => s.id === sessionId ? updated : s))
        }).catch(() => {})
      }
    } catch (err) {
      const stopped = controller.signal.aborted
      update(message => ({ ...message, streaming: false, stopped, isError: !stopped,
        content: stopped ? (message.content || 'Response stopped.')
          : `${message.content}${message.content ? '\n\n' : ''}Error: ${err.message}`,
      }))
    } finally {
      if (activeRequest.current?.controller === controller) {
        activeRequest.current = null
        setIsLoading(false)
      }
    }
  }, [currentSessionId, chatHistory, sessions])

  const messages = chatHistory[currentSessionId] ?? []

  return (
    <div className="app-layout">
      <Sidebar
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={handleSelectSession}
        onCreateSession={handleCreateSession}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
        documents={currentSession?.documents ?? []}
        onUpload={handleUpload}
        onDelete={handleDelete}
        uploadStatus={uploadStatus}
        onIngestUrl={handleIngestUrl}
        urlIngestStatus={urlIngestStatus}
      />
      <ChatWindow
        notice={apiError || storageError}
        onStop={handleStop}
        messages={messages}
        isLoading={isLoading}
        onSend={handleSend}
        sessionName={currentSession?.name ?? ''}
        onClearChat={handleClearChat}
      />
    </div>
  )
}
