
import { useEffect, useRef, useState } from "react";
import "./Chatbot.css";
import { askAssistant } from "../api/venues";

// Icons used for accessibility facilities
const CHAT_FACILITY_ICON = {
  accessible_toilet: "🚻",
  accessible_parking: "🅿",
  accessible_transport_stop: "🚋",
  accessible_change_facility: "♿",
};

// Names used for accessibility facilities
const CHAT_FACILITY_LABEL = {
  accessible_toilet: "Toilet",
  accessible_parking: "Parking",
  accessible_transport_stop: "Transport",
  accessible_change_facility: "Change facility",
};

// Returns a symbol based on the facility status
function chatFacilityStatusSymbol(display) {
  if (display === "at_venue" || display === "within_limit") return "✓";
  if (display === "beyond_limit") return "!";
  if (display === "not_available") return "✕";
  return "?";
}

// Displays accessibility facilities in the chat results
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
        <a className="chat-result-card-link" href={event.href || event.event_url}>
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

// Displays suggested questions that users can select
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

// Keys used to save chatbot preferences for the current session
const GREETING_DISMISSED_KEY = "sportable-chat-greeting-dismissed";
const SPEAK_ANSWERS_KEY = "sportable-chat-speak-answers";

// Prepares previous chat messages to send to the backend
function buildHistory(messages) {
  return messages
    .filter((message) => !message.isGreeting && !message.isError)
    .map((message) => ({
      role: message.sender === "user" ? "user" : "assistant",
      content: message.text,
    }));
}

// Checks whether the browser supports voice input and speech output
const SpeechRecognitionAPI =
  typeof window !== "undefined"
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : null;

const SPEECH_RECOGNITION_SUPPORTED = Boolean(SpeechRecognitionAPI);

const SPEECH_SYNTHESIS_SUPPORTED =
  typeof window !== "undefined" && "speechSynthesis" in window;

// Displays the microphone icon
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

export default function ChatBot() {
  // Stores the chatbot's current state and messages
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

  // Stores the microphone and spoken-answer settings
  const [isListening, setIsListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [inputSource, setInputSource] = useState("text");
  const [speakAnswers, setSpeakAnswers] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);

  // References to the input, messages and speech controls
  const messageListRef = useRef(null);
  const inputRef = useRef(null);
  const recognitionRef = useRef(null);
  const utteranceRef = useRef(null);

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

  // Shows the greeting if it has not been dismissed
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

  // Restores the user's Speak Answers setting
  useEffect(() => {
    try {
      setSpeakAnswers(sessionStorage.getItem(SPEAK_ANSWERS_KEY) === "true");
    } catch {
      // Speak Answers remains off if storage is unavailable
    }
  }, []);

  // Stops listening and speaking when the component is removed
  useEffect(() => {
    return () => {
      if (recognitionRef.current) recognitionRef.current.stop();
      if (SPEECH_SYNTHESIS_SUPPORTED) window.speechSynthesis.cancel();
    };
  }, []);

  // Hides the greeting and saves the choice for this session
  function dismissGreeting() {
    setShowGreeting(false);
    try {
      sessionStorage.setItem(GREETING_DISMISSED_KEY, "true");
    } catch {
      // Continues if session storage is unavailable
    }
  }

  // Stops the spoken answer
  function stopSpeaking() {
    if (SPEECH_SYNTHESIS_SUPPORTED) {
      window.speechSynthesis.cancel();
    }

    setIsSpeaking(false);
    setIsPaused(false);
  }

  // Reads the assistant's answer aloud
  function speak(text) {
    if (!SPEECH_SYNTHESIS_SUPPORTED || !speakAnswers || !text) return;

    stopSpeaking();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-AU";

    // Uses an Australian English voice if one is available
    const voices = window.speechSynthesis.getVoices();
    const enAuVoice = voices.find((voice) => voice.lang === "en-AU");
    if (enAuVoice) utterance.voice = enAuVoice;

    // Updates the status when speech starts or ends
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

  // Pauses or resumes the spoken answer
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

  // Turns Speak Answers on or off
  function toggleSpeakAnswers() {
    const next = !speakAnswers;
    setSpeakAnswers(next);
    if (!next) stopSpeaking();

    try {
      sessionStorage.setItem(SPEAK_ANSWERS_KEY, String(next));
    } catch {
      // Continues if session storage is unavailable
    }
  }

  // Starts listening to the user's voice
  function startListening() {
    if (!SPEECH_RECOGNITION_SUPPORTED || isListening) return;

    // Stops spoken answers before using the microphone
    stopSpeaking();
    setVoiceError("");

    const recognition = new SpeechRecognitionAPI();
    recognition.lang = "en-AU";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => setIsListening(true);

    // Converts recognised speech into text in the input field
    recognition.onresult = (event) => {
      let transcript = "";
      for (let i = 0; i < event.results.length; i += 1) {
        transcript += event.results[i][0].transcript;
      }

      setInputValue(transcript);
      setInputSource("voice");
    };

    // Shows a message if voice recognition fails
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

    // Resets the microphone when listening ends
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

  // Stops listening to the user's voice
  function stopListening() {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  }

  // Starts or stops voice input when the microphone is clicked
  function handleMicClick() {
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  }

  // Opens or closes the chatbot and stops any active voice features
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

  // Sends a question to the backend and displays the response
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
      // Sends the question, chat history and input type
      const response = await askAssistant({
        question: text,
        history,
        mode: resolvedMode,
      });

      // Adds the assistant's reply and related results
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

      // Reads the reply if Speak Answers is enabled
      speak(response.answer);
    } catch (error) {
      // Shows an error if the assistant request fails
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

  // Sends the question entered in the input field
  function handleSubmit(event) {
    event.preventDefault();
    sendQuestion(inputValue.trim());
  }

  // Updates the input when the user types
  function handleInputChange(event) {
    setInputValue(event.target.value);
    setInputSource("text");
    stopSpeaking();
  }

  // Stops voice activity or closes the chat when Escape is pressed
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
      {/* Displays the chat window when it is open */}
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

          {/* Option to turn spoken answers on or off */}
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

                  {/* Shows results, links and suggested questions */}
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

          {/* Buttons to pause, resume or stop a spoken answer */}
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

          {/* Shows an error message if voice input fails */}
          {voiceError && (
            <p className="chat-voice-error" role="alert">
              {voiceError}
            </p>
          )}

          {/* Microphone, message input and send button */}
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

      {/* Greeting shown when the chatbot is closed */}
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
  );
}
