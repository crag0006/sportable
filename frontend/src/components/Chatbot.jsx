
import { useEffect, useRef, useState } from "react";
import "./Chatbot.css";
import { askAssistant } from "../api/venues";

// Icons used to show accessibility facilities.
const CHAT_FACILITY_ICON = {
  accessible_toilet: "🚻",
  accessible_parking: "🅿",
  accessible_transport_stop: "🚋",
  accessible_change_facility: "♿",
};

// Names used for accessibility facilities.
const CHAT_FACILITY_LABEL = {
  accessible_toilet: "Toilet",
  accessible_parking: "Parking",
  accessible_transport_stop: "Transport",
  accessible_change_facility: "Change facility",
};

// Returns a symbol for each facility status.
function chatFacilityStatusSymbol(display) {
  if (display === "at_venue" || display === "within_limit") return "✓";
  if (display === "beyond_limit") return "!";
  if (display === "not_available") return "✕";
  return "?";
}

// Displays accessibility facilities in chat results.
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

// Shows a venue with its location and facilities.
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

      {venue.suburb && (
        <p className="chat-result-card-sub">{venue.suburb}</p>
      )}

      <ChatFacilityChips facilities={venue.facilities} />

      {venue.href && (
        <a className="chat-result-card-link" href={venue.href}>
          View venue
        </a>
      )}
    </div>
  );
}

// Shows event details and registration links.
function ChatEventCard({ event }) {
  const title = event.title || event.name || "Event";
  const venueName = event.venue?.name || event.venue_name;
  const venueUnmatched = event.venue && event.venue.matched === false;

  const subParts = [venueName, event.when, event.price].filter(Boolean);

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

      {subParts.length > 0 && (
        <p className="chat-result-card-sub">{subParts.join(" · ")}</p>
      )}

      {venueUnmatched && event.venue.message && (
        <p className="chat-result-card-sub chat-result-card-note">
          {event.venue.message}
        </p>
      )}

      <ChatFacilityChips facilities={event.facilities} />

      <div className="chat-result-card-actions">
        {(event.href || event.event_url) && (
          <a
            className="chat-result-card-link"
            href={event.href || event.event_url}
          >
            View event
          </a>
        )}

        {event.registration && (
          <a className="chat-result-card-link" href={event.registration}>
            Register
          </a>
        )}

        {event.external && (
          <a className="chat-result-card-link" href={event.external}>
            View on publisher site
          </a>
        )}
      </div>
    </div>
  );
}

// Shows venue and event cards in the assistant's response.
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

// Displays general links without repeating event-specific links.
function ChatLinks({ links }) {
  const visibleLinks = (links || []).filter(
    (link) => link.kind !== "registration" && link.kind !== "publisher"
  );

  if (visibleLinks.length === 0) return null;

  return (
    <div className="chat-message-links">
      {visibleLinks.map((link, index) => (
        <a key={index} href={link.href} className="chat-message-link">
          {link.label}
        </a>
      ))}
    </div>
  );
}

// Displays the data sources used in an answer.
function ChatSources({ sources }) {
  if (!sources || sources.length === 0) return null;

  return (
    <p className="chat-message-sources">
      Sources: {sources.map((source) => source.name).join(", ")}
    </p>
  );
}

// Displays suggested questions the user can select.
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

let nextId = 1;

// Creates a chat message with its sender and a unique ID.
function makeMessage(sender, text, extra = {}) {
  nextId += 1;
  return { id: nextId, sender, text, ...extra };
}

const GREETING_DISMISSED_KEY = "sportable-chat-greeting-dismissed";
const SPEAK_ANSWERS_KEY = "sportable-chat-speak-answers";

// Prepares conversation history without greeting or error messages.
function buildHistory(messages) {
  return messages
    .filter((message) => !message.isGreeting && !message.isError)
    .map((message) => ({
      role: message.sender === "user" ? "user" : "assistant",
      content: message.text,
    }));
}

// Checks whether the browser supports voice input.
const SpeechRecognitionAPI =
  typeof window !== "undefined"
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : null;

const SPEECH_RECOGNITION_SUPPORTED = Boolean(SpeechRecognitionAPI);
const SPEECH_SYNTHESIS_SUPPORTED =
  typeof window !== "undefined" && "speechSynthesis" in window;

// Displays the microphone icon.
function MicIcon({ listening }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" fill={listening ? "currentColor" : "none"} />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

// Main chatbot component.
export default function ChatBot() {
  const [isOpen, setIsOpen] = useState(false);
  const [showGreeting, setShowGreeting] = useState(false);

  const [messages, setMessages] = useState([
    makeMessage(
      "bot",
      "Hi! I'm the SportAble assistant. Ask me about accessible venues or events — for example, \"Basketball near Preston with an accessible toilet?\"",
      { isGreeting: true }
    ),
  ]);

  const [inputValue, setInputValue] = useState("");
  const [isBotTyping, setIsBotTyping] = useState(false);

  // Tracks microphone and spoken-answer settings.
  const [isListening, setIsListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [inputSource, setInputSource] = useState("text");
  const [speakAnswers, setSpeakAnswers] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);

  // References to chat messages, input and voice controls.
  const messageListRef = useRef(null);
  const inputRef = useRef(null);
  const recognitionRef = useRef(null);
  const utteranceRef = useRef(null);

  // Scrolls automatically to the latest chat message.
  useEffect(() => {
    if (messageListRef.current) {
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
    }
  }, [messages, isBotTyping, isOpen]);

  // Focuses the input field when the chatbot opens.
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  // Shows a greeting unless it has already been dismissed.
  useEffect(() => {
    let dismissed = false;

    try {
      dismissed = sessionStorage.getItem(GREETING_DISMISSED_KEY) === "true";
    } catch {
    }

    if (dismissed || isOpen) return;

    const timer = setTimeout(() => setShowGreeting(true), 1800);
    return () => clearTimeout(timer);
  }, [isOpen]);

  // Restores the spoken-answer setting for this browser session.
  useEffect(() => {
    try {
      setSpeakAnswers(sessionStorage.getItem(SPEAK_ANSWERS_KEY) === "true");
    } catch {
    }
  }, []);

  // Stops microphone and speech activity when the component is removed.
  useEffect(() => {
    return () => {
      if (recognitionRef.current) recognitionRef.current.stop();
      if (SPEECH_SYNTHESIS_SUPPORTED) window.speechSynthesis.cancel();
    };
  }, []);

  // Hides the greeting and saves the choice.
  function dismissGreeting() {
    setShowGreeting(false);

    try {
      sessionStorage.setItem(GREETING_DISMISSED_KEY, "true");
    } catch {
    }
  }

  // Stops reading an answer aloud.
  function stopSpeaking() {
    if (SPEECH_SYNTHESIS_SUPPORTED) {
      window.speechSynthesis.cancel();
    }

    setIsSpeaking(false);
    setIsPaused(false);
  }

  // Reads the assistant's answer aloud when enabled.
  function speak(text) {
    if (!SPEECH_SYNTHESIS_SUPPORTED || !speakAnswers || !text) return;

    stopSpeaking();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-AU";

    const voices = window.speechSynthesis.getVoices();
    const enAuVoice = voices.find((voice) => voice.lang === "en-AU");

    if (enAuVoice) utterance.voice = enAuVoice;

    utterance.onstart = () => setIsSpeaking(true);

    utterance.onend = () => {
      setIsSpeaking(false);
      setIsPaused(false);
    };

    utterance.onerror = () => {
      setIsSpeaking(false);
      setIsPaused(false);
    };

    utteranceRef.current = utterance;
    window.speechSynthesis.speak(utterance);
  }

  // Pauses or resumes a spoken answer.
  function togglePauseSpeaking() {
    if (!SPEECH_SYNTHESIS_SUPPORTED || !isSpeaking) return;

    if (isPaused) {
      window.speechSynthesis.resume();
      setIsPaused(false);
    } else {
      window.speechSynthesis.pause();
      setIsPaused(true);
    }
  }

  // Turns spoken answers on or off.
  function toggleSpeakAnswers() {
    const next = !speakAnswers;
    setSpeakAnswers(next);

    if (!next) stopSpeaking();

    try {
      sessionStorage.setItem(SPEAK_ANSWERS_KEY, String(next));
    } catch {
    }
  }

  // Starts converting the user's speech into text.
  function startListening() {
    if (!SPEECH_RECOGNITION_SUPPORTED || isListening) return;

    stopSpeaking();
    setVoiceError("");

    const recognition = new SpeechRecognitionAPI();
    recognition.lang = "en-AU";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => setIsListening(true);

    // Puts recognised words into the message field.
    recognition.onresult = (event) => {
      let transcript = "";

      for (let i = 0; i < event.results.length; i += 1) {
        transcript += event.results[i][0].transcript;
      }

      setInputValue(transcript);
      setInputSource("voice");
    };

    // Shows an error message if voice input fails.
    recognition.onerror = (event) => {
      setIsListening(false);

      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setVoiceError(
          "Microphone access was denied. You can still type your question below."
        );
      } else if (event.error === "no-speech") {
        setVoiceError(
          "Didn't catch that — no speech heard. Try again or type your question."
        );
      } else if (event.error === "network") {
        setVoiceError(
          "Voice input needs a network connection right now. Please type your question instead."
        );
      } else {
        setVoiceError("Voice input didn't work. Please type your question instead.");
      }

      if (inputRef.current) inputRef.current.focus();
    };

    // Resets the microphone when listening stops.
    recognition.onend = () => {
      setIsListening(false);
      recognitionRef.current = null;
      if (inputRef.current) inputRef.current.focus();
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
    } catch {
      setIsListening(false);
      setVoiceError("Couldn't start voice input. Please type your question instead.");
      if (inputRef.current) inputRef.current.focus();
    }
  }

  // Stops microphone recording.
  function stopListening() {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  }

  // Starts or stops the microphone when clicked.
  function handleMicClick() {
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  }

  // Opens or closes chat and stops active voice features.
  function handleToggle() {
    setIsOpen((open) => {
      const next = !open;

      if (!next) {
        stopListening();
        stopSpeaking();
      }

      return next;
    });

    dismissGreeting();
  }

  // Sends a question and conversation history to the assistant.
  async function sendQuestion(text, { mode } = {}) {
    if (!text || isBotTyping) return;

    const resolvedMode = mode || inputSource;
    const history = buildHistory(messages);

    stopSpeaking();
    setMessages((prev) => [...prev, makeMessage("user", text)]);
    setInputValue("");
    setInputSource("text");
    setIsBotTyping(true);

    try {
      const response = await askAssistant({
        question: text,
        history,
        mode: resolvedMode,
      });

      setMessages((prev) => [
        ...prev,
        makeMessage("bot", response.answer, {
          kind: response.kind,
          results: response.results,
          links: response.links,
          sources: response.sources,
          suggestedQuestions: response.suggestedQuestions,
        }),
      ]);

      speak(response.answer);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        makeMessage(
          "bot",
          error.message ||
            "Sorry, I couldn't reach the assistant right now. Please try again.",
          { isError: true }
        ),
      ]);
    } finally {
      setIsBotTyping(false);
    }
  }

  // Sends the typed message when the form is submitted.
  function handleSubmit(event) {
    event.preventDefault();
    sendQuestion(inputValue.trim());
  }

  // Updates the input and stops any spoken reply.
  function handleInputChange(event) {
    setInputValue(event.target.value);
    setInputSource("text");
    stopSpeaking();
  }

  // Uses Escape to stop voice activity or close the chatbot.
  function handleKeyDown(event) {
    if (event.key !== "Escape") return;

    if (isListening) {
      stopListening();
      return;
    }

    if (isSpeaking) {
      stopSpeaking();
      return;
    }

    setIsOpen(false);
  }

  return (
    <div className="chat-widget">
      {/* Main chat window */}
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

          {/* Option to enable spoken answers */}
          {SPEECH_SYNTHESIS_SUPPORTED && (
            <label className="chat-speak-toggle">
              <input
                type="checkbox"
                checked={speakAnswers}
                onChange={toggleSpeakAnswers}
              />
              Speak answers
            </label>
          )}

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

                  {message.sender === "bot" && (
                    <>
                      <ChatResults results={message.results} />
                      <ChatLinks links={message.links} />
                      <ChatSources sources={message.sources} />
                      <ChatSuggestedQuestions
                        questions={message.suggestedQuestions}
                        onPick={(question) => sendQuestion(question, { mode: "text" })}
                        disabled={isBotTyping}
                      />
                    </>
                  )}
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

          {/* Controls for spoken answers */}
          {isSpeaking && (
            <div className="chat-speaking-bar" role="status">
              <span aria-hidden="true">🔊</span>
              <span className="chat-speaking-label">
                {isPaused ? "Paused" : "Speaking…"}
              </span>

              <button type="button" onClick={togglePauseSpeaking}>
                {isPaused ? "Resume" : "Pause"}
              </button>

              <button type="button" onClick={stopSpeaking}>
                Stop
              </button>
            </div>
          )}

          {voiceError && (
            <p className="chat-voice-error" role="alert">
              {voiceError}
            </p>
          )}

          {/* Message input, microphone and send button */}
          <form className="chat-panel-input-row" onSubmit={handleSubmit}>
            {SPEECH_RECOGNITION_SUPPORTED && (
              <button
                type="button"
                className={`chat-mic-button${isListening ? " chat-mic-button--active" : ""}`}
                onClick={handleMicClick}
                aria-pressed={isListening}
                aria-label={isListening ? "Stop voice input" : "Ask by voice"}
                title={isListening ? "Listening… tap to stop" : "Ask by voice"}
              >
                <MicIcon listening={isListening} />
              </button>
            )}

            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={handleInputChange}
              placeholder={isListening ? "Listening…" : "Type a message..."}
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

          <p className="chat-disclaimer">
            SportAble Assistant is an AI and can make mistakes. Please verify
            important information.
          </p>
        </div>
      )}

      {/* Greeting shown before the chat is opened */}
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

      {/* Floating button used to open or close the chatbot */}
      <button
        type="button"
        className="chat-fab"
        onClick={handleToggle}
        aria-label={isOpen ? "Close chat" : "Open chat"}
        aria-expanded={isOpen}
      >
        <span className="chat-fab-ring" aria-hidden="true" />

        {isOpen ? (
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="6" y1="6" x2="18" y2="18" />
            <line x1="18" y1="6" x2="6" y2="18" />
          </svg>
        ) : (
          <>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
            </svg>

            {/* Shows the assistant label on larger screens */}
            <span className="chat-fab-label">Ask SportAble Assistant</span>
          </>
        )}
      </button>
    </div>
  );
}
