import { useEffect, useRef, useState } from "react";
import "./Chatbot.css";
import { askAssistant } from "../api/venues";

// Icons used for accessibility facilities
const CHAT_FACILITY_ICON = {
  accessible_toilet: "🚻",
  accessible_parking: "🅿",
  accessible_transport_stop: "🚋",
  accessible_change_facility: "♿"
};

// Names used for accessibility facilities
const CHAT_FACILITY_LABEL = {
  accessible_toilet: "Toilet",
  accessible_parking: "Parking",
  accessible_transport_stop: "Transport",
  accessible_change_facility: "Change facility"
};

// Returns a symbol based on the facility status
function chatFacilityStatusSymbol(display) {
  if (display === "at_venue" || display === "within_limit") return "✓";
  if (display === "beyond_limit") return "!";
  if (display === "not_available") return "✕";
  return "?";
}

// Displays the accessibility facilities in the chat results
function ChatFacilityChips({ facilities }) {
  if (!facilities || facilities.length === 0) return null;

  return (
    <div className="chat-result-facilities">
      {facilities.map((facility) => (
        <span
          key={facility.type}
          className={`chat-result-facility chat-result-facility--${
            facility.display || "unknown"
          }`}
          title={facility.message}
        >
          <span aria-hidden="true">
            {CHAT_FACILITY_ICON[facility.type] || "•"}
          </span>
          {CHAT_FACILITY_LABEL[facility.type] || facility.type}
          <span aria-hidden="true" className="chat-result-facility-symbol">
            {chatFacilityStatusSymbol(facility.display)}
          </span>
        </span>
      ))}
    </div>
  );
}

// Displays a venue card in the chatbot results
function ChatVenueCard({ venue }) {
  return (
    <div className="chat-result-card">
      <div className="chat-result-card-top">
        <strong className="chat-result-card-name">{venue.name}</strong>
        {venue.distance_m != null && (
          <span className="chat-result-card-distance">
            {venue.distance_m} m away
          </span>
        )}
      </div>

      {venue.suburb && <p className="chat-result-card-sub">{venue.suburb}</p>}

      <ChatFacilityChips facilities={venue.facilities} />

      {venue.href && (
        <a className="chat-result-card-link" href={venue.href}>
          View venue
        </a>
      )}
    </div>
  );
}

// Displays an event card in the chatbot results
function ChatEventCard({ event }) {
  const title = event.title || event.name || "Event";
  const venueName = event.venue?.name || event.venue_name;

  return (
    <div className="chat-result-card">
      <div className="chat-result-card-top">
        <strong className="chat-result-card-name">{title}</strong>
        {event.distance_m != null && (
          <span className="chat-result-card-distance">
            {event.distance_m} m away
          </span>
        )}
      </div>

      {venueName && <p className="chat-result-card-sub">{venueName}</p>}

      <ChatFacilityChips facilities={event.facilities} />

      {(event.href || event.event_url) && (
        <a
          className="chat-result-card-link"
          href={event.href || event.event_url}
        >
          View event
        </a>
      )}
    </div>
  );
}

// Displays the venue and event results returned by the assistant
function ChatResults({ results }) {
  const venues = results?.venues || [];
  const events = results?.events || [];

  if (venues.length === 0 && events.length === 0) return null;

  return (
    <div className="chat-result-cards">
      {venues.map((venue) => (
        <ChatVenueCard key={venue.id} venue={venue} />
      ))}
      {events.map((event) => (
        <ChatEventCard key={event.id} event={event} />
      ))}
    </div>
  );
}

// Displays links provided in the assistant's response
function ChatLinks({ links }) {
  if (!links || links.length === 0) return null;

  return (
    <div className="chat-message-links">
      {links.map((link, index) => (
        <a key={index} href={link.href} className="chat-message-link">
          {link.label}
        </a>
      ))}
    </div>
  );
}

// Shows the data sources used for the assistant's response
function ChatSources({ sources }) {
  if (!sources || sources.length === 0) return null;

  return (
    <p className="chat-message-sources">
      Sources: {sources.map((source) => source.name).join(", ")}
    </p>
  );
}

// Displays suggested questions that users can click
function ChatSuggestedQuestions({ questions, onPick, disabled }) {
  if (!questions || questions.length === 0) return null;

  return (
    <div className="chat-suggested-questions">
      {questions.map((question, index) => (
        <button
          key={index}
          type="button"
          className="chat-suggested-chip"
          onClick={() => onPick(question)}
          disabled={disabled}
        >
          {question}
        </button>
      ))}
    </div>
  );
}

// Creates a chat message with an ID, sender and text
let nextId = 1;
function makeMessage(sender, text, extra = {}) {
  nextId += 1;
  return { id: nextId, sender, text, ...extra };
}

// Key used to remember if the greeting was dismissed
const GREETING_DISMISSED_KEY = "sportable-chat-greeting-dismissed";

// Prepares the previous chat messages to send to the backend
function buildHistory(messages) {
  return messages
    .filter((message) => !message.isGreeting && !message.isError)
    .map((message) => ({
      role: message.sender === "user" ? "user" : "assistant",
      content: message.text
    }));
}

export default function ChatBot() {
  // Stores the chatbot's current state and messages
  const [isOpen, setIsOpen] = useState(false);
  const [showGreeting, setShowGreeting] = useState(false);
  const [messages, setMessages] = useState([
    makeMessage(
      "bot",
      'Hi! I\'m the SportAble assistant. Ask me about accessible venues or events — for example, "Basketball near Preston with an accessible toilet?"',
      { isGreeting: true }
    )
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isBotTyping, setIsBotTyping] = useState(false);

  // References to the message area and input field
  const messageListRef = useRef(null);
  const inputRef = useRef(null);

  // Scrolls to the latest message automatically
  useEffect(() => {
    if (messageListRef.current) {
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
    }
  }, [messages, isBotTyping, isOpen]);

  // Focuses the input field when the chat opens
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  // Shows the greeting only if it has not been dismissed
  useEffect(() => {
    let dismissed = false;
    try {
      dismissed = sessionStorage.getItem(GREETING_DISMISSED_KEY) === "true";
    } catch {
      // Continues if session storage is unavailable
    }

    if (dismissed || isOpen) return;

    const timer = setTimeout(() => setShowGreeting(true), 1800);
    return () => clearTimeout(timer);
  }, [isOpen]);

  // Hides the greeting and saves the choice for this session
  function dismissGreeting() {
    setShowGreeting(false);
    try {
      sessionStorage.setItem(GREETING_DISMISSED_KEY, "true");
    } catch {
      // The greeting can still be closed if storage is unavailable
    }
  }

  // Opens or closes the chatbot
  function handleToggle() {
    setIsOpen((open) => !open);
    dismissGreeting();
  }

  // Sends a question to the backend and displays the response
  async function sendQuestion(text) {
    if (!text || isBotTyping) return;

    const history = buildHistory(messages);

    // Adds the user's question to the conversation
    setMessages((prev) => [...prev, makeMessage("user", text)]);
    setInputValue("");
    setIsBotTyping(true);

    try {
      const response = await askAssistant({ question: text, history });

      // Adds the assistant's reply and any related results
      setMessages((prev) => [
        ...prev,
        makeMessage("bot", response.answer, {
          kind: response.kind,
          results: response.results,
          links: response.links,
          sources: response.sources,
          suggestedQuestions: response.suggestedQuestions
        })
      ]);
    } catch (error) {
      // Shows an error message if the backend request fails
      setMessages((prev) => [
        ...prev,
        makeMessage(
          "bot",
          error.message ||
            "Sorry, I couldn't reach the assistant right now. Please try again.",
          { isError: true }
        )
      ]);
    } finally {
      setIsBotTyping(false);
    }
  }

  // Sends the message entered in the input field
  function handleSubmit(event) {
    event.preventDefault();
    sendQuestion(inputValue.trim());
  }

  // Closes the chatbot when Escape is pressed
  function handleKeyDown(event) {
    if (event.key === "Escape") {
      setIsOpen(false);
    }
  }

  return (
    <div className="chat-widget">
      {/* Displays the chat panel when it is open */}
      {isOpen && (
        <div
          className="chat-panel"
          role="dialog"
          aria-modal="false"
          aria-label="SportAble assistant chat"
          onKeyDown={handleKeyDown}
        >
          {/* Chat heading and close button */}
          <div className="chat-panel-header">
            <div>
              <div className="chat-panel-title">SportAble Assistant</div>
              <div className="chat-panel-subtitle">
                Ask about - Venues and Events
              </div>
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

          {/* Displays the conversation messages */}
          <div
            className="chat-panel-messages"
            ref={messageListRef}
            aria-live="polite"
          >
            {messages.map((message) => (
              <div
                key={message.id}
                className={`chat-bubble-row chat-bubble-row--${message.sender}`}
              >
                <div
                  className={`chat-bubble chat-bubble--${message.sender}${
                    message.isError ? " chat-bubble--error" : ""
                  }`}
                >
                  <p className="chat-bubble-text">{message.text}</p>

                  {/* Shows results, links and suggestions in the bot's reply */}
                  {message.sender === "bot" && (
                    <>
                      <ChatResults results={message.results} />
                      <ChatLinks links={message.links} />
                      <ChatSources sources={message.sources} />
                      <ChatSuggestedQuestions
                        questions={message.suggestedQuestions}
                        onPick={sendQuestion}
                        disabled={isBotTyping}
                      />
                    </>
                  )}
                </div>
              </div>
            ))}

            {/* Shows typing dots while waiting for a response */}
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

          {/* Message input and send button */}
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

      {/* Greeting message shown when the chat is closed */}
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

      {/* Floating button to open or close the chatbot */}
      <button
        type="button"
        className="chat-fab"
        onClick={handleToggle}
        aria-label={isOpen ? "Close chat" : "Open chat"}
        aria-expanded={isOpen}
      >
        <span className="chat-fab-ring" aria-hidden="true" />
        {isOpen ? (
          <svg
            width="26"
            height="26"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <line x1="6" y1="6" x2="18" y2="18" />
            <line x1="18" y1="6" x2="6" y2="18" />
          </svg>
        ) : (
          <svg
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        )}
      </button>
    </div>
  );
}
