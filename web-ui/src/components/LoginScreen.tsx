import { FormEvent, useState } from "react";
type Props = {
  onLogin: (username: string, password: string) => Promise<void>;
  initialError?: string;
};

export function LoginScreen({ onLogin, initialError = "" }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(initialError);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const normalizedUsername = username.trim();
    if (!normalizedUsername || !password) {
      setError("Enter your user name and password.");
      return;
    }

    setIsSubmitting(true);
    setError("");
    try {
      await onLogin(normalizedUsername, password);
      setPassword("");
    } catch (loginError) {
      setError((loginError as Error).message || "Authentication failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="loginShell">
      <form className="loginCard" onSubmit={submit}>
        <div>
          <p className="eyebrow">AES Workbench</p>
          <h1>Sign in</h1>
          <p className="muted">
            Sign in with an AES account. Authentication sessions are stored
            securely by the AES server.
          </p>
        </div>

        <label>
          User name
          <input
            autoFocus
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="engineer"
            autoComplete="username"
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>

        {error ? <div className="errorBox">{error}</div> : null}

        <button disabled={isSubmitting} type="submit">
          {isSubmitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
