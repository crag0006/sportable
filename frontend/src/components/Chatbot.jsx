import { useEffect, useRef, useState } from 'react'

async function getBotReply(userText) {
  // Simulated "thinking" delay so the typing indicator is visible.
  await new Promise((resolve) => setTimeout(resolve, 700))
  return "Thanks for your message! I can't answer questions yet — this chat is just a preview of how the assistant will work once it's connected to the backend."
}

let nextId = 1
function makeMessage(sender, text) {
  nextId += 1
  return { id: nextId, sender, text }
}

const GREETING_DISMISSED_KEY = 'sportable-chat-greeting-dismissed'

export default function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false)
  const [showGreeting, setShowGreeting] = useState(false)
  const [messages, setMessages] = useState([
    makeMessage('bot', "Hi! I'm the SportAble assistant (preview). Ask me anything — I can't give real answers yet, but go ahead and try it out."),
  ])
  const [inputValue, setInputValue] = useState('')
  const [isBotTyping, setIsBotTyping] = useState(false)

  const messageListRef = useRef(null)
  const inputRef = useRef(null)

  // Keep the thread scrolled to the latest message.
  useEffect(() => {
    if (messageListRef.current) {
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight
    }
  }, [messages, isBotTyping, isOpen])

  // Focus the input whenever the panel opens.
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isOpen])

  useEffect(() => {
    let dismissed = false
    try {
      dismissed = sessionStorage.getItem(GREETING_DISMISSED_KEY) === 'true'
    } catch {
      
    }
    if (dismissed || isOpen) return

    const timer = setTimeout(() => setShowGreeting(true), 1800)
    return () => clearTimeout(timer)
  }, [isOpen])

  function dismissGreeting() {
    setShowGreeting(false)
    try {
      sessionStorage.setItem(GREETING_DISMISSED_KEY, 'true')
    } catch {
      // Not critical.
    }
  }


  function handleToggle() {
    setIsOpen((open) => !open)
    dismissGreeting()
  }

  async function handleSubmit(event) {
    event.preventDefault()
    const text = inputValue.trim()
    if (!text || isBotTyping) return

    setMessages((prev) => [...prev, makeMessage('user', text)])
    setInputValue('')
    setIsBotTyping(true)

    try {
      const replyText = await getBotReply(text)
      setMessages((prev) => [...prev, makeMessage('bot', replyText)])
    } finally {
      setIsBotTyping(false)
    }
  }

  function handleKeyDown(event) {
    if (event.key === 'Escape') {
      setIsOpen(false)
    }
  }

  return (
    <div className="chat-widget">
      {isOpen && (
        <div
          className="chat-panel"
          role="dialog"
          aria-modal="false"
          aria-label="SportAble assistant chat"
          onKeyDown={handleKeyDown}
        >
          <div className="chat-panel-header">
            <div>
              <div className="chat-panel-title">SportAble Assistant</div>
              <div className="chat-panel-subtitle">Ask about - Venues and Events</div>
            </div>
            <button
              type="button"
              className="chat-panel-close"
              onClick={handleToggle}
              aria-label="Close chat"
            >
              ✕
            </button>
          </div>

          <div className="chat-panel-messages" ref={messageListRef} aria-live="polite">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`chat-bubble-row chat-bubble-row--${message.sender}`}
              >
                <div className={`chat-bubble chat-bubble--${message.sender}`}>
                  {message.text}
                </div>
              </div>
            ))}

            {isBotTyping && (
              <div className="chat-bubble-row chat-bubble-row--bot">
                <div className="chat-bubble chat-bubble--bot chat-bubble--typing">
                  <span className="chat-typing-dot" />
                  <span className="chat-typing-dot" />
                  <span className="chat-typing-dot" />
                </div>
              </div>
            )}
          </div>

          <form className="chat-panel-input-row" onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              placeholder="Type a message..."
              aria-label="Type a message"
              autoComplete="off"
            />
            <button
              type="submit"
              className="chat-panel-send"
              disabled={!inputValue.trim() || isBotTyping}
              aria-label="Send message"
            >
              ➤
            </button>
          </form>
        </div>
      )}

      {showGreeting && !isOpen && (
        <div className="chat-greeting">
          <button
            type="button"
            className="chat-greeting-close"
            onClick={dismissGreeting}
            aria-label="Dismiss"
          >
            ✕
          </button>
          <p>
            👋 Need help finding an accessible venue or event? Chat with us!
          </p>
        </div>
      )}

      <button
        type="button"
        className="chat-fab"
        onClick={handleToggle}
        aria-label={isOpen ? 'Close chat' : 'Open chat'}
        aria-expanded={isOpen}
      >
        <span className="chat-fab-ring" aria-hidden="true" />
        {isOpen ? (
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="6" y1="6" x2="18" y2="18" />
            <line x1="18" y1="6" x2="6" y2="18" />
          </svg>
        ) : (
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        )}
      </button>
    </div>
  )
}
