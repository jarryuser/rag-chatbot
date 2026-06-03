import { useState, useCallback, useEffect } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ChatWindow from './components/ChatWindow.jsx'

const API = ''

export default function App() {
  // All sessions: [{ id, name, created_at, documents[] }]
  const [sessions, setSessions] = useState([])
  // ID of the currently open session
  const [currentSessionId, setCurrentSessionId] = useState(null)
  // Per-session chat history: { [sessionId]: [{ role, content, sources? }] }
  const [chatHistory, setChatHistory] = useState({})

  const [isLoading, setIsLoading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState(null)
  const [urlIngestStatus, setUrlIngestStatus] = useState(null)

  // Current session object derived from state
  const currentSession = sessions.find(s => s.id === currentSessionId) ?? null

  // ── Load sessions on mount, auto-create default if none ──────────────────
  useEffect(() => {
    fetch(`${API}/api/sessions`)
      .then(r => r.json())
      .then(async data => {
        let list = data.sessions ?? []
        if (list.length === 0) {
          // First launch — create a default session automatically
          const res = await fetch(`${API}/api/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: 'New Chat' }),
          })
          const session = await res.json()
          list = [session]
        }
        setSessions(list)
        setCurrentSessionId(list[0].id)
      })
      .catch(() => {})
  }, [])

  // ── Session handlers ──────────────────────────────────────────────────────
  const handleCreateSession = useCallback(async () => {
    const res = await fetch(`${API}/api/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'New Chat' }),
    })
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
    const updated = await res.json()
    setSessions(prev => prev.map(s => s.id === id ? updated : s))
  }, [])

  const handleDeleteSession = useCallback(async (id) => {
    const res = await fetch(`${API}/api/sessions/${id}`, { method: 'DELETE' })
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
    if (!currentSessionId) return
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
      setUploadStatus('error')
      console.error(err)
      setTimeout(() => setUploadStatus(null), 4000)
    }
  }, [currentSessionId])

  // ── Ingest URL handler ────────────────────────────────────────────────────
  const handleIngestUrl = useCallback(async (url) => {
    if (!currentSessionId || !url.trim()) return
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
      console.error('Delete failed:', err)
    }
  }, [currentSessionId])

  // ── Clear conversation handler ────────────────────────────────────────────
  const handleClearChat = useCallback(() => {
    setChatHistory(prev => ({ ...prev, [currentSessionId]: [] }))
  }, [currentSessionId])

  // ── Chat handler ──────────────────────────────────────────────────────────
  const handleSend = useCallback(async (question) => {
    if (!question.trim() || isLoading || !currentSessionId) return

    const priorMessages = (chatHistory[currentSessionId] ?? [])
      .slice(-10)
      .map(({ role, content }) => ({ role, content }))

    const isFirstMessage =
      priorMessages.length === 0 &&
      (sessions.find(s => s.id === currentSessionId)?.name ?? '') === 'New Chat'

    const sessionId = currentSessionId

    setChatHistory(prev => ({
      ...prev,
      [sessionId]: [...(prev[sessionId] ?? []), { role: 'user', content: question }],
    }))
    setIsLoading(true)

    try {
      const res = await fetch(`${API}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, session_id: sessionId, history: priorMessages }),
      })

      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Request failed')
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let firstToken = true

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop()

        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data: ')) continue
          let event
          try { event = JSON.parse(line.slice(6)) } catch { continue }

          if (event.type === 'token') {
            if (firstToken) {
              firstToken = false
              setIsLoading(false)
              setChatHistory(prev => ({
                ...prev,
                [sessionId]: [
                  ...(prev[sessionId] ?? []),
                  { role: 'assistant', content: event.content, sources: '', streaming: true },
                ],
              }))
            } else {
              setChatHistory(prev => {
                const msgs = prev[sessionId] ?? []
                const last = msgs[msgs.length - 1]
                return {
                  ...prev,
                  [sessionId]: [
                    ...msgs.slice(0, -1),
                    { ...last, content: last.content + event.content },
                  ],
                }
              })
            }
          } else if (event.type === 'done') {
            setChatHistory(prev => {
              const msgs = prev[sessionId] ?? []
              const last = msgs[msgs.length - 1]
              return {
                ...prev,
                [sessionId]: [
                  ...msgs.slice(0, -1),
                  { ...last, sources: event.sources, streaming: false },
                ],
              }
            })
            if (isFirstMessage) {
              fetch(`${API}/api/sessions/${sessionId}/auto-name`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question }),
              })
                .then(r => r.ok ? r.json() : null)
                .then(updated => {
                  if (updated) setSessions(prev => prev.map(s => s.id === sessionId ? updated : s))
                })
                .catch(() => {})
            }
          } else if (event.type === 'error') {
            throw new Error(event.detail)
          }
        }
      }
    } catch (err) {
      setChatHistory(prev => ({
        ...prev,
        [sessionId]: [
          ...(prev[sessionId] ?? []),
          { role: 'assistant', content: `Error: ${err.message}`, isError: true },
        ],
      }))
    } finally {
      setIsLoading(false)
    }
  }, [isLoading, currentSessionId])

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
        messages={messages}
        isLoading={isLoading}
        onSend={handleSend}
        sessionName={currentSession?.name ?? ''}
        onClearChat={handleClearChat}
      />
    </div>
  )
}
