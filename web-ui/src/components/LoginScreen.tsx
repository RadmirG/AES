import { FormEvent, useState } from "react";
import type { WorkbenchUser } from "../types";

type Props = {
  onLogin: (user: WorkbenchUser) => void;
};

export function LoginScreen({ onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const normalizedUsername = username.trim();
    if (!normalizedUsername) {
      setError("Please enter a user name.");
      return;
    }

    onLogin({
      username: normalizedUsername,
      displayName: displayName.trim() || normalizedUsername,
      signedInAt: new Date().toISOString(),
    });
  }

  return (
    <main className="loginShell">
      <form className="loginCard" onSubmit={submit}>
        <div>
          <p className="eyebrow">AES Workbench</p>
          <h1>Sign in</h1>
          <p className="muted">
            Local prototype login. Your saved chats are stored in this browser
            under the selected user name.
          </p>
        </div>

        <label>
          User name
          <input
            autoFocus
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="radmir"
          />
        </label>

        <label>
          Display name
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="optional"
          />
        </label>

        {error ? <div className="errorBox">{error}</div> : null}

        <button type="submit">Open Workbench</button>
      </form>
    </main>
  );
}
