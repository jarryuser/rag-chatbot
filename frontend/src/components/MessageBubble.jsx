import ReactMarkdown from 'react-markdown'

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'

  return (
    <div className={`message ${isUser ? 'user' : 'assistant'}`}>
      {/* Avatar */}
      <div className={`avatar ${isUser ? 'user-avatar' : 'assistant-avatar'}`}>
        {isUser ? 'You' : 'AI'}
      </div>

      <div className="bubble-wrapper">
        {/* Message content — render markdown for assistant messages */}
        <div className={`bubble ${message.isError ? 'error-bubble' : ''}`}>
          {isUser
            ? <p>{message.content}</p>
            : <ReactMarkdown>{message.content}</ReactMarkdown>
          }
        </div>

        {/* Sources citation shown below assistant messages */}
        {!isUser && message.sources && (
          <p className="sources">
            <span className="sources-label">📎 Sources:</span> {message.sources}
          </p>
        )}
      </div>
    </div>
  )
}
