import { useRef, useState } from 'react'

// Icons
const FileIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </svg>
)

const UploadIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="16 16 12 12 8 16" />
    <line x1="12" y1="12" x2="12" y2="21" />
    <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3" />
  </svg>
)

const TrashIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    <path d="M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
  </svg>
)

const PlusIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
)

const PencilIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
)

const ChatIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
)

const GlobeIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="2" y1="12" x2="22" y2="12" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
)

const ArrowRightIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="5" y1="12" x2="19" y2="12" />
    <polyline points="12 5 19 12 12 19" />
  </svg>
)

export default function Sidebar({
  sessions, currentSessionId,
  onSelectSession, onCreateSession, onRenameSession, onDeleteSession,
  documents, onUpload, onDelete, uploadStatus,
  onIngestUrl, urlIngestStatus,
}) {
  const inputRef = useRef(null)
  const [editingId, setEditingId] = useState(null)   // session being renamed
  const [editingName, setEditingName] = useState('')
  const [confirmDeleteSession, setConfirmDeleteSession] = useState(null)
  const [confirmDeleteDoc, setConfirmDeleteDoc] = useState(null)
  const [urlInput, setUrlInput] = useState('')

  // File upload
  const handleFileChange = (e) => {
    const file = e.target.files[0]
    if (file) { onUpload(file); e.target.value = '' }
  }

  // Session rename
  const startRename = (session) => {
    setEditingId(session.id)
    setEditingName(session.name)
  }

  const commitRename = () => {
    if (editingName.trim()) onRenameSession(editingId, editingName.trim())
    setEditingId(null)
  }

  // Session delete (two-click confirm)
  const handleDeleteSession = (id) => {
    if (confirmDeleteSession === id) {
      onDeleteSession(id)
      setConfirmDeleteSession(null)
    } else {
      setConfirmDeleteSession(id)
      setTimeout(() => setConfirmDeleteSession(c => c === id ? null : c), 3000)
    }
  }

  const handleUrlSubmit = (e) => {
    e.preventDefault()
    if (urlInput.trim()) {
      onIngestUrl(urlInput.trim())
      setUrlInput('')
    }
  }

  // Document delete (two-click confirm)
  const handleDeleteDoc = (name) => {
    if (confirmDeleteDoc === name) {
      onDelete(name)
      setConfirmDeleteDoc(null)
    } else {
      setConfirmDeleteDoc(name)
      setTimeout(() => setConfirmDeleteDoc(c => c === name ? null : c), 3000)
    }
  }

  return (
    <aside className="sidebar">
      {/* Header */}
      <div className="sidebar-header">
        <span className="logo">💬</span>
        <h1 className="sidebar-title">RAG Chatbot</h1>
      </div>

      {/* Session list */}
      <div className="sessions-section">
        <div className="section-header">
          <span className="section-label">Chats</span>
          <button className="new-chat-btn" onClick={onCreateSession} title="New chat">
            <PlusIcon />
          </button>
        </div>

        <div className="session-list">
          {sessions.map(s => (
            <div
              key={s.id}
              className={`session-item ${s.id === currentSessionId ? 'active' : ''}`}
              onClick={() => { if (editingId !== s.id) onSelectSession(s.id) }}
            >
              <ChatIcon />

              {/* Inline rename input */}
              {editingId === s.id ? (
                <input
                  className="session-rename-input"
                  value={editingName}
                  onChange={e => setEditingName(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={e => {
                    if (e.key === 'Enter') commitRename()
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  autoFocus
                  onClick={e => e.stopPropagation()}
                />
              ) : (
                <span
                  className="session-name"
                  title={s.name}
                  onDoubleClick={e => { e.stopPropagation(); startRename(s) }}
                >
                  {s.name}
                </span>
              )}

              {/* Rename button — visible on hover/active, hidden during inline edit */}
              {editingId !== s.id && (
                <button
                  className="delete-btn rename-btn"
                  onClick={e => { e.stopPropagation(); startRename(s) }}
                  title="Rename chat"
                >
                  <PencilIcon />
                </button>
              )}

              {/* Delete session button */}
              <button
                className={`delete-btn ${confirmDeleteSession === s.id ? 'confirm' : ''}`}
                onClick={e => { e.stopPropagation(); handleDeleteSession(s.id) }}
                title={confirmDeleteSession === s.id ? 'Click again to confirm' : 'Delete chat'}
              >
                {confirmDeleteSession === s.id ? '?' : <TrashIcon />}
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="sidebar-divider" />

      {/* Document upload for current session */}
      <div className="section-header">
        <span className="section-label">Documents</span>
      </div>

      <div
        className={`upload-zone ${uploadStatus === 'uploading' ? 'uploading' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDrop={e => { e.preventDefault(); onUpload(e.dataTransfer.files[0]) }}
        onDragOver={e => e.preventDefault()}
        role="button" tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && inputRef.current?.click()}
      >
        <UploadIcon />
        <p className="upload-label">
          {uploadStatus === 'uploading' ? 'Indexing…' : 'Click or drag file here'}
        </p>
        <p className="upload-hint">PDF, DOCX, TXT, MD, CSV, XLS · max 50 MB</p>
        <input ref={inputRef} type="file" accept=".pdf,.docx,.txt,.md,.csv,.xls,.xlsx"
          className="hidden-input" onChange={handleFileChange} />
      </div>

      {uploadStatus === 'success' && <p className="status-badge success">✅ Indexed</p>}
      {uploadStatus === 'error'   && <p className="status-badge error">❌ Upload failed</p>}

      {/* URL ingestion */}
      <form className="url-ingest-form" onSubmit={handleUrlSubmit}>
        <div className="url-ingest-row">
          <GlobeIcon />
          <input
            className="url-ingest-input"
            type="url"
            placeholder="Paste URL to index…"
            value={urlInput}
            onChange={e => setUrlInput(e.target.value)}
            disabled={urlIngestStatus === 'loading'}
          />
          <button
            className="url-ingest-btn"
            type="submit"
            disabled={!urlInput.trim() || urlIngestStatus === 'loading'}
            title="Index this URL"
          >
            <ArrowRightIcon />
          </button>
        </div>
      </form>
      {urlIngestStatus === 'loading' && <p className="status-badge">⏳ Fetching…</p>}
      {urlIngestStatus === 'success' && <p className="status-badge success">✅ Indexed</p>}
      {urlIngestStatus === 'error'   && <p className="status-badge error">❌ Failed</p>}

      {/* Document list for current session */}
      {documents.length > 0 && (
        <div className="doc-list">
          {documents.map(name => (
            <div key={name} className="doc-item">
              <FileIcon />
              <span className="doc-name" title={name}>{name}</span>
              <button
                className={`delete-btn ${confirmDeleteDoc === name ? 'confirm' : ''}`}
                onClick={() => handleDeleteDoc(name)}
                title={confirmDeleteDoc === name ? 'Click again to confirm' : 'Remove document'}
              >
                {confirmDeleteDoc === name ? '?' : <TrashIcon />}
              </button>
            </div>
          ))}
        </div>
      )}
    </aside>
  )
}
