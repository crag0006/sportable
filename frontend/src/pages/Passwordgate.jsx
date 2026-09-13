import { useState, useEffect, useRef } from "react";
import "./PasswordGate.css";

const SITE_PASSWORD = "1234";

// sessionStorage = re-asks every new browser tab/session.
const STORAGE_KEY = "sportable_authenticated";

export default function PasswordGate({ children }) {
  const [authenticated, setAuthenticated] = useState(
    () => sessionStorage.getItem(STORAGE_KEY) === "true"
  );
  const [password, setPassword] = useState("");
  const [error, setError] = useState(false);
  const [shake, setShake] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!authenticated) {
      inputRef.current?.focus();
    }
  }, [authenticated]);

  function handleSubmit(e) {
    e.preventDefault();

    if (password === SITE_PASSWORD) {
      sessionStorage.setItem(STORAGE_KEY, "true");
      setAuthenticated(true);
      setError(false);
    } else {
      setError(true);
      setPassword("");
      setShake(true);
      setTimeout(() => setShake(false), 400);
      inputRef.current?.focus();
    }
  }

  if (authenticated) {
    return children;
  }

  return (
    <div className="password-gate">
      <form
        className={`password-gate__card ${shake ? "password-gate__card--shake" : ""}`}
        onSubmit={handleSubmit}
      >
        <h1 className="password-gate__title">SportAble Melbourne</h1>
        <p className="password-gate__subtitle">
          This site is password protected. Enter the password to continue.
        </p>

        <label className="password-gate__label" htmlFor="site-password">
          Password
        </label>
        <input
          ref={inputRef}
          id="site-password"
          type="password"
          className="password-gate__input"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
            if (error) setError(false);
          }}
          autoComplete="off"
          aria-invalid={error}
          aria-describedby={error ? "password-error" : undefined}
        />

        {error && (
          <p id="password-error" className="password-gate__error" role="alert">
            Incorrect password. Please try again.
          </p>
        )}

        <button type="submit" className="password-gate__button">
          Enter
        </button>
      </form>
    </div>
  );
}