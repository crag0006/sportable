import { useEffect, useRef, useState } from "react";
import "./ReadAloud.css";

// Checks whether the browser supports text-to-speech
function isSpeechSupported() {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    typeof window.SpeechSynthesisUtterance === "function"
  );
}

// Hides text visually while keeping it available to screen readers
const srOnlyStyle = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0
};

export default function ReadAloud({ summary }) {
  // Stores the reading status, current sentence and messages
  const [status, setStatus] = useState("idle");
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [showUnsupported, setShowUnsupported] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const queueRef = useRef([]);

  // Removes empty sentences from the summary
  const sentences = (summary || []).filter(
    (line) => line && line.trim().length > 0
  );
  const hasContent = sentences.length > 0;

  // Stops reading when the user leaves the page
  useEffect(() => {
    return () => {
      if (isSpeechSupported()) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  // Starts reading the summary from the beginning
  function speakFromStart() {
    if (!isSpeechSupported()) {
      setShowUnsupported(true);
      return;
    }

    // Stops any speech that is already playing
    window.speechSynthesis.cancel();

    // Creates a speech item for each sentence
    const queue = sentences.map(
      (sentence) => new window.SpeechSynthesisUtterance(sentence)
    );

    queue.forEach((utterance, index) => {
      utterance.rate = 0.92;
      utterance.lang = "en-AU";

      // Highlights the sentence currently being read
      utterance.onstart = () => {
        setCurrentIndex(index);
      };

      // Resets the reading status after the last sentence
      utterance.onend = () => {
        if (index === queue.length - 1) {
          setStatus("idle");
          setCurrentIndex(-1);
          setAnnouncement("Finished reading.");
        }
      };

      // Resets the reading status if speech fails
      utterance.onerror = () => {
        setStatus("idle");
        setCurrentIndex(-1);
      };
    });

    // Adds all sentences to the speech queue
    queueRef.current = queue;
    queue.forEach((utterance) => window.speechSynthesis.speak(utterance));

    setStatus("playing");
    setShowUnsupported(false);
    setAnnouncement("Reading aloud.");
  }

  // Starts reading or resumes paused speech
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

  // Pauses the speech
  function handlePause() {
    if (!isSpeechSupported()) return;
    window.speechSynthesis.pause();
    setStatus("paused");
    setAnnouncement("Paused.");
  }

  // Stops reading and clears the current sentence
  function handleStop() {
    if (!isSpeechSupported()) return;
    window.speechSynthesis.cancel();
    setStatus("idle");
    setCurrentIndex(-1);
    setAnnouncement("Stopped.");
  }

  // Hides the Read Aloud controls if there is no summary
  if (!hasContent) {
    return null;
  }

  return (
    <div className="read-aloud">
      {/* Buttons to play, pause and stop the reading */}
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
          <span aria-hidden="true">▶</span>{" "}
          {status === "paused" ? "Resume" : "Read aloud"}
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

      {/* Announces the reading status to screen reader users */}
      <p style={srOnlyStyle} role="status" aria-live="polite">
        {announcement}
      </p>

      {/* Shows a message if the browser does not support Read Aloud */}
      {showUnsupported && (
        <p className="read-aloud-unsupported" role="alert">
          Read Aloud isn't supported in this browser. Try a recent version of
          Chrome, Edge, or Safari instead.
        </p>
      )}

      {/* Displays the summary and highlights the current sentence */}
      {status !== "idle" && (
        <p className="read-aloud-transcript">
          {sentences.map((sentence, index) => (
            <span
              key={index}
              className={
                index === currentIndex ? "read-aloud-current" : undefined
              }
            >
              {sentence}{" "}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
