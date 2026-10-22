import { useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { normalizeCitations } from '../chat.js'
import { remarkCitations } from '../citations.js'

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  const citations = normalizeCitations(message.citations)
  const excerpts = useRef({})

  const openExcerpt = (event, id) => {
    const excerpt = excerpts.current[id]
    if (!excerpt) return
    event.preventDefault()
    excerpt.open = true
    excerpt.querySelector('summary')?.focus()
    excerpt.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
  }

  return (
    <div className={`message ${isUser ? 'user' : 'assistant'}`}>
      <div className={`avatar ${isUser ? 'user-avatar' : 'assistant-avatar'}`}>
        {isUser ? 'You' : 'AI'}
      </div>
      <div className="bubble-wrapper">
        <div className={`bubble ${message.isError ? 'error-bubble' : ''}`}>
          {isUser ? <p>{message.content}</p> : (
            <ReactMarkdown
              remarkPlugins={[[remarkCitations, { ids: citations.map(citation => citation.id) }]]}
              components={{ a: ({ href, children }) => {
                const id = /^#source-(\d+)$/.exec(href || '')?.[1]
                return id && citations.some(citation => citation.id === Number(id))
                  ? <a href={href} onClick={event => openExcerpt(event, id)} aria-label={`View source ${id}`}>{children}</a>
                  : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
              } }}
            >{message.content}</ReactMarkdown>
          )}
          {!isUser && message.streaming && <span className="streaming-cursor" aria-hidden="true" />}
        </div>
        {message.stopped && <p className="sources">Response stopped</p>}
        {!isUser && citations.length > 0 ? (
          <section className="source-excerpts" aria-label="Source passages">
            <p className="sources-label">Source passages</p>
            <p className="source-hint">Passages provided to the model. Open a source to check the answer.</p>
            {citations.map(citation => (
              <details key={citation.id} className="source-excerpt" ref={node => { excerpts.current[citation.id] = node }}>
                <summary>
                  <span className="source-number">[{citation.id}]</span> {citation.source}
                  {citation.page != null && <span> · Page {citation.page_label || citation.page}</span>}
                  {citation.row != null && <span> · Row {citation.row}</span>}
                </summary>
                <blockquote>{citation.text}</blockquote>
                {citation.url && <a href={citation.url} target="_blank" rel="noopener noreferrer">Open web page</a>}
              </details>
            ))}
          </section>
        ) : !isUser && message.sources && (
          <p className="sources"><span className="sources-label">Sources:</span> {message.sources}</p>
        )}
      </div>
    </div>
  )
}
