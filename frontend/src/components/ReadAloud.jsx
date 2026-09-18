import { useEffect, useRef, useState } from "react";
import "./ReadAloud.css";

function isSpeechSupported() {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    typeof window.SpeechSynthesisUtterance === "function"
  );
}

// A screen-reader-only paragraph, styled inline rather than via a shared
// class name — this session has already hit one CSS class-name collision
// (.legend-icon), so a commonly-reused name like ".visually-hidden" is
// deliberately avoided here.
const srOnlyStyle = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

// summary: an array of short sentences to read one at a time, so the
// sentence currently being spoken can be highlighted on screen (AC3.3.3).
// Renders nothing if there's no summary content to read.
export default function ReadAloud({ summary }) {
  const [status, setStatus] = useState("idle"); // idle | playing | paused
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [showUnsupported, setShowUnsupported] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const queueRef = useRef([]);

  const sentences = (summary || []).filter((line) => line && line.trim().length > 0);
  const hasContent = sentences.length > 0;

  // Read Aloud must never keep talking after the user has left the page —
  // cancel any speech in progress when this component unmounts.
  useEffect(() => {
    return () => {
      if (isSpeechSupported()) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  function speakFromStart() {
    if (!isSpeechSupported()) {
      setShowUnsupported(true);
      return;
    }

    window.speechSynthesis.cancel();

    const queue = sentences.map((sentence) => new window.SpeechSynthesisUtterance(sentence));

    queue.forEach((utterance, index) => {
      utterance.rate = 0.92;
      utterance.lang = "en-AU";

      utterance.onstart = () => {
        setCurrentIndex(index);
      };

      utterance.onend = () => {
        if (index === queue.length - 1) {
          setStatus("idle");
          setCurrentIndex(-1);
          setAnnouncement("Finished reading.");
        }
      };

      utterance.onerror = () => {
        setStatus("idle");
        setCurrentIndex(-1);
      };
    });

    queueRef.current = queue;
    queue.forEach((utterance) => window.speechSynthesis.speak(utterance));

    setStatus("playing");
    setShowUnsupported(false);
    setAnnouncement("Reading aloud.");
  }

  function handlePlay() {
    if (!isSpeechSupported()) {
      setShowUnsupported(true);
      return;
    }

    if (status === "paused") {
      window.speechSynthesis.resume();
      setStatus("playing");
      setAnnouncement("Resumed.");
      return;
    }

    speakFromStart();
  }

  function handlePause() {
    if (!isSpeechSupported()) return;
    window.speechSynthesis.pause();
    setStatus("paused");
    setAnnouncement("Paused.");
  }

  function handleStop() {
    if (!isSpeechSupported()) return;
    window.speechSynthesis.cancel();
    setStatus("idle");
    setCurrentIndex(-1);
    setAnnouncement("Stopped.");
  }

  if (!hasContent) {
    return null;
  }

  return (
    <div className="read-aloud">
      <div className="read-aloud-controls">
        <button
          type="button"
          className="read-aloud-button read-aloud-button--play"
          onClick={handlePlay}
          disabled={status === "playing"}
          aria-pressed={status === "playing"}
          aria-label={
            status === "playing"
              ? "Reading aloud, already playing"
              : status === "paused"
              ? "Resume reading aloud"
              : "Read this page's summary aloud"
          }
        >
          <span aria-hidden="true">▶</span> {status === "paused" ? "Resume" : "Read aloud"}
        </button>

        <button
          type="button"
          className="read-aloud-button read-aloud-button--pause"
          onClick={handlePause}
          disabled={status !== "playing"}
          aria-label="Pause reading aloud"
        >
          <span aria-hidden="true">⏸</span> Pause
        </button>

        <button
          type="button"
          className="read-aloud-button read-aloud-button--stop"
          onClick={handleStop}
          disabled={status === "idle"}
          aria-label="Stop reading aloud"
        >
          <span aria-hidden="true">⏹</span> Stop
        </button>
      </div>

      {/* Announces state changes once, politely — never repeats itself, so
          it doesn't create confusing duplicate audio for screen-reader
          users (AC3.3.4). */}
      <p style={srOnlyStyle} role="status" aria-live="polite">
        {announcement}
      </p>

      {showUnsupported && (
        <p className="read-aloud-unsupported" role="alert">
          Read Aloud isn't supported in this browser. Try a recent version of Chrome, Edge, or
          Safari instead.
        </p>
      )}

      {status !== "idle" && (
        <p className="read-aloud-transcript">
          {sentences.map((sentence, index) => (
            <span
              key={index}
              className={index === currentIndex ? "read-aloud-current" : undefined}
            >
              {sentence}{" "}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
