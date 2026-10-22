export const HISTORY_KEY = 'rag-chatbot.history.v1'
export const ACTIVE_SESSION_KEY = 'rag-chatbot.active-session.v1'
const MAX_MESSAGES = 200

export function loadHistory(storage) {
  const saved = JSON.parse(storage.getItem(HISTORY_KEY) || '{}')
  if (!saved || typeof saved !== 'object' || Array.isArray(saved)) return {}
  return Object.fromEntries(Object.entries(saved)
    .filter(([id, messages]) => /^[0-9a-f-]{36}$/.test(id) && Array.isArray(messages))
    .map(([id, messages]) => [id, messages
      .filter(m => m && ['user', 'assistant'].includes(m.role) && typeof m.content === 'string')
      .slice(-MAX_MESSAGES)
      .map(m => ({ ...m, id: m.id || crypto.randomUUID(), streaming: false,
        stopped: Boolean(m.stopped || m.streaming),
        citations: normalizeCitations(m.citations),
        content: m.content || 'Response interrupted. Please try again.',
      }))]))
}

export function saveHistory(storage, history) {
  const saved = Object.fromEntries(Object.entries(history)
    .map(([id, messages]) => [id, messages.slice(-MAX_MESSAGES)]))
  storage.setItem(HISTORY_KEY, JSON.stringify(saved))
}

export function updateMessage(history, sessionId, messageId, update) {
  if (!history[sessionId]) return history
  return { ...history, [sessionId]: history[sessionId].map(message =>
    message.id === messageId ? update(message) : message) }
}

function parseEvent(frame) {
  const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:'))
    .map(line => line.slice(5).trimStart()).join('\n')
  return data ? JSON.parse(data) : null
}

export async function* readEvents(body) {
  if (!body) throw new Error('The server did not return a response stream')
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop()
      for (const frame of frames) {
        const event = parseEvent(frame)
        if (event) yield event
      }
      if (done) {
        const event = parseEvent(buffer)
        if (event) yield event
        break
      }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}


export function normalizeCitations(citations) {
  if (!Array.isArray(citations)) return []
  return citations.filter(citation => citation && Number.isInteger(citation.id) && citation.id > 0 &&
    typeof citation.source === 'string' && typeof citation.text === 'string')
    .slice(0, 12).map(citation => ({
      ...citation,
      page: Number.isInteger(citation.page) ? citation.page : null,
      page_label: typeof citation.page_label === 'string' ? citation.page_label : null,
      row: Number.isInteger(citation.row) ? citation.row : null,
      url: typeof citation.url === 'string' && /^https?:\/\//.test(citation.url) ? citation.url : null,
    }))
}

export function restoreSession(storage, sessions) {
  let saved
  try { saved = storage.getItem(ACTIVE_SESSION_KEY) } catch { /* Storage can be disabled */ }
  return sessions.find(session => session.id === saved)?.id ?? sessions[0]?.id ?? null
}
