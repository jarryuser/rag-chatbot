import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble.jsx'
import ChatInput from './ChatInput.jsx'

// ── Icons ─────────────────────────────────────────────────────────────────────
const EraseIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 20H7L3 16l10-10 7 7-2.5 2.5" />
    <path d="M6.0001 10.0001L14 18" />
  </svg>
)

// Animated thinking dots shown while waiting for the API
const ThinkingIndicator = () => (
  <div className="message assistant">
    <div className="avatar assistant-avatar">AI</div>
    <div className="bubble thinking">
      <span className="dot" /><span className="dot" /><span className="dot" />
    </div>
  </div>
)

export default function ChatWindow({ messages, isLoading, onSend, sessionName, onClearChat }) {
  const bottomRef = useRef(null)

  // Auto-scroll to the latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  return (
    <main className="chat-window">
      {/* Header */}
      <div className="chat-header">
        <span className="chat-title">{sessionName}</span>
        {messages.length > 0 && (
          <button
            className="clear-chat-btn"
            onClick={onClearChat}
            title="Clear conversation"
          >
            <EraseIcon />
            <span>Clear</span>
          </button>
        )}
      </div>

      <div className="messages-area">
        {messages.length === 0 && !isLoading && (
          <div className="empty-state">
            <p className="empty-title">Upload a document and start asking questions</p>
            <p className="empty-hint">
              The chatbot will answer based on the content of your files.
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {isLoading && !messages.some(m => m.streaming) && <ThinkingIndicator />}

        {/* Invisible anchor for auto-scroll */}
        <div ref={bottomRef} />
      </div>

      <ChatInput onSend={onSend} isLoading={isLoading} />
    </main>
  )
}
