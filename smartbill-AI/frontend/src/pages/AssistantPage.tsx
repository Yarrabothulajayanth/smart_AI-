import { useEffect, useRef, useState } from 'react'
import { apiRequest } from '../api'
import { ErrorMessage, Icon, LoadingState } from '../components/Common'
import type {
  AssistantDocument,
  AssistantReply,
  AssistantStatus,
} from '../types'

interface ConversationMessage {
  id: number
  role: 'assistant' | 'user'
  text: string
  sources?: AssistantReply['sources']
}

const suggestedQuestions = [
  "How much did the shop sell today?",
  "Show this month's best-selling products.",
  'Find a product by name or barcode.',
  'ఈ రోజు అమ్మకాలు ఎంత?',
]

export function AssistantPage() {
  const [status, setStatus] = useState<AssistantStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [documents, setDocuments] = useState<AssistantDocument[]>([])
  const [documentError, setDocumentError] = useState<string | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [loadingDocuments, setLoadingDocuments] = useState(true)
  const [busyDocumentId, setBusyDocumentId] = useState<number | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const messageEnd = useRef<HTMLDivElement>(null)

  const loadDocuments = async () => {
    setLoadingDocuments(true)
    setDocumentError(null)
    try {
      setDocuments(await apiRequest<AssistantDocument[]>('/assistant/documents'))
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : 'Could not load documents.')
    } finally {
      setLoadingDocuments(false)
    }
  }

  useEffect(() => {
    let active = true
    apiRequest<AssistantStatus>('/assistant/status')
      .then((result) => active && setStatus(result))
      .catch((error: unknown) => {
        if (active) {
          setStatusError(error instanceof Error ? error.message : 'Could not check AI configuration.')
        }
      })
    void loadDocuments()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  const sendMessage = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || sending) return
    setQuestion('')
    setSending(true)
    setMessages((current) => [
      ...current,
      { id: Date.now(), role: 'user', text: trimmed },
    ])
    try {
      const reply = await apiRequest<AssistantReply>('/assistant/chat', {
        method: 'POST',
        body: JSON.stringify({ question: trimmed }),
      })
      setMessages((current) => [
        ...current,
        {
          id: Date.now() + 1,
          role: 'assistant',
          text: reply.answer,
          sources: reply.sources,
        },
      ])
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: Date.now() + 1,
          role: 'assistant',
          text: error instanceof Error ? error.message : 'The assistant could not answer.',
        },
      ])
    } finally {
      setSending(false)
    }
  }

  const submitQuestion = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void sendMessage(question)
  }

  const uploadDocument = async (file: File | undefined) => {
    if (!file) return
    if (file.size > 1_000_000) {
      setDocumentError('Choose a text file smaller than 1 MB.')
      if (fileInput.current) fileInput.current.value = ''
      return
    }
    setUploading(true)
    setDocumentError(null)
    try {
      const content = await file.text()
      await apiRequest<AssistantDocument>('/assistant/documents', {
        method: 'POST',
        body: JSON.stringify({ filename: file.name, content }),
      })
      await loadDocuments()
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : 'Document upload failed.')
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const removeDocument = async (document: AssistantDocument) => {
    if (!window.confirm(`Remove ${document.filename} from assistant search?`)) return
    setBusyDocumentId(document.id)
    setDocumentError(null)
    try {
      await apiRequest<void>(`/assistant/documents/${document.id}`, {
        method: 'DELETE',
      })
      setDocuments((current) => current.filter((item) => item.id !== document.id))
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : 'Document removal failed.')
    } finally {
      setBusyDocumentId(null)
    }
  }

  return (
    <div className="page-stack">
      <div className="page-heading-row assistant-page-heading">
        <div>
          <h1>AI Assistant</h1>
          <p>Ask questions about actual shop records or your reference documents.</p>
        </div>
        <button
          className="button button-secondary"
          disabled={messages.length === 0 || sending}
          onClick={() => setMessages([])}
        >
          Clear conversation
        </button>
      </div>

      <div className="assistant-layout">
        <section className="panel assistant-chat-panel" aria-label="Assistant chat">
          <div className="assistant-chat-heading">
            <div className="assistant-avatar"><Icon name="assistant" size={20} /></div>
            <div>
              <h2>Shop assistant</h2>
              <p>English and Telugu · Read-only access</p>
            </div>
            <span className={`assistant-availability${status?.chat_configured ? ' assistant-ready' : ''}`}>
              {status?.chat_configured ? 'Ready' : 'Not configured'}
            </span>
          </div>

          {statusError && <ErrorMessage message={statusError} />}
          {!statusError && !status?.chat_configured && (
            <div className="assistant-config-note" role="status">
              AI is optional and is not configured yet. Set the compatible provider
              endpoint and chat model in the backend environment to enable chat.
              Billing and the rest of the application remain available.
            </div>
          )}

          <div className="assistant-messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="assistant-welcome">
                <span className="assistant-welcome-icon"><Icon name="assistant" size={25} /></span>
                <h2>How can I help with your shop?</h2>
                <p>Financial figures come from SmartBill records, not model estimates.</p>
                <div className="assistant-suggestions">
                  {suggestedQuestions.map((item) => (
                    <button
                      className="assistant-suggestion"
                      key={item}
                      disabled={!status?.chat_configured || sending}
                      onClick={() => void sendMessage(item)}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message) => (
              <article
                className={`assistant-message assistant-message-${message.role}`}
                key={message.id}
              >
                <div className="assistant-message-label">
                  {message.role === 'user' ? 'You' : 'SmartBill assistant'}
                </div>
                <div className="assistant-message-text">{message.text}</div>
                {message.sources && message.sources.length > 0 && (
                  <div className="assistant-sources">
                    <strong>Sources</strong>
                    {message.sources.map((source, index) => (
                      <span className="assistant-source" key={`${source.label}-${index}`}>
                        {source.label}{source.detail ? ` · ${source.detail}` : ''}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            ))}
            {sending && <LoadingState label="Checking shop information…" />}
            <div ref={messageEnd} />
          </div>

          <form className="assistant-composer" onSubmit={submitQuestion}>
            <label className="visually-hidden" htmlFor="assistant-question">Ask a question</label>
            <textarea
              id="assistant-question"
              maxLength={2000}
              placeholder="Ask about sales, products, invoices, customers, or shop documents…"
              rows={2}
              value={question}
              disabled={!status?.chat_configured || sending}
              onChange={(event) => setQuestion(event.target.value)}
            />
            <button
              className="button button-primary"
              disabled={!status?.chat_configured || sending || !question.trim()}
            >
              {sending ? 'Working…' : 'Send'}
            </button>
          </form>
          <p className="assistant-privacy-note">
            Questions and the minimum relevant context are sent to the configured external provider.
            This chat history stays in this browser tab and is not saved by SmartBill.
          </p>
        </section>

        <aside className="panel assistant-documents-panel">
          <div className="panel-heading">
            <div>
              <h2>Shop documents</h2>
              <p>Markdown, CSV, or plain text · up to 1 MB each</p>
            </div>
          </div>
          <div className="assistant-document-upload">
            <input
              accept=".txt,.md,.csv,text/plain,text/markdown,text/csv"
              className="visually-hidden"
              ref={fileInput}
              type="file"
              onChange={(event) => void uploadDocument(event.target.files?.[0])}
            />
            <button
              className="button button-secondary"
              disabled={!status?.embeddings_configured || uploading}
              onClick={() => fileInput.current?.click()}
            >
              {uploading ? <><span className="spinner spinner-small" /> Indexing…</> : 'Add document'}
            </button>
            {!status?.embeddings_configured && (
              <span>Configure an embeddings model to add documents.</span>
            )}
          </div>
          {documentError && <ErrorMessage message={documentError} />}
          {loadingDocuments ? (
            <LoadingState label="Loading documents…" />
          ) : documents.length === 0 ? (
            <div className="assistant-documents-empty">
              <Icon name="invoices" size={20} />
              <p>No reference documents have been added.</p>
            </div>
          ) : (
            <ul className="assistant-document-list">
              {documents.map((document) => (
                <li key={document.id}>
                  <div className="assistant-document-icon"><Icon name="invoices" size={17} /></div>
                  <div className="assistant-document-copy">
                    <strong>{document.filename}</strong>
                    <span>{document.chunk_count} text chunk(s)</span>
                  </div>
                  <button
                    className="icon-button danger-icon"
                    aria-label={`Remove ${document.filename}`}
                    disabled={busyDocumentId === document.id}
                    onClick={() => void removeDocument(document)}
                  >
                    <Icon name="delete" size={16} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="assistant-document-note">
            Document text is embedded by the configured provider and relevant passages may be
            sent to it when answering document questions.
          </p>
        </aside>
      </div>
    </div>
  )
}
