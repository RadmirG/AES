import { useEffect, useMemo, useRef, useState } from "react";
import { loadBackendLogs } from "../backend";
import type { BackendLogEntry } from "../types";

type Props = {
  active: boolean;
};

export function BackendLogPanel({ active }: Props) {
  const [entries, setEntries] = useState<BackendLogEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const viewportRef = useRef<HTMLDivElement>(null);
  const afterRef = useRef(0);

  useEffect(() => {
    if (!active || paused) {
      return;
    }
    let cancelled = false;

    async function poll() {
      try {
        const response = await loadBackendLogs(afterRef.current);
        if (cancelled) {
          return;
        }
        setError("");
        setNote(response.note);
        afterRef.current = response.next_after;
        if (response.entries.length) {
          setEntries((current) =>
            deduplicate([...current, ...response.entries]).slice(-1000),
          );
        }
      } catch (pollError) {
        if (!cancelled) {
          setError((pollError as Error).message);
        }
      }
    }

    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [active, paused]);

  useEffect(() => {
    if (!paused && viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [entries, paused]);

  const visibleEntries = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return entries;
    }
    return entries.filter((entry) =>
      `${entry.component} ${entry.level} ${entry.logger} ${entry.message}`
        .toLowerCase()
        .includes(normalized),
    );
  }, [entries, query]);

  return (
    <section className="backendLogs" aria-label="AES backend logs">
      <header className="backendLogsHeader">
        <div>
          <strong>AES backend logs</strong>
          <small>Live, authenticated, redacted LangGraph orchestration stream</small>
        </div>
        <div className="backendLogActions">
          <input
            aria-label="Filter backend logs"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter logs..."
            value={query}
          />
          <button onClick={() => setPaused((value) => !value)} type="button">
            {paused ? "Resume" : "Pause"}
          </button>
          <button onClick={() => setEntries([])} type="button">Clear view</button>
        </div>
      </header>

      {error ? <div className="errorBox">{error}</div> : null}
      <div className="backendLogViewport" ref={viewportRef}>
        {visibleEntries.length ? (
          visibleEntries.map((entry) => (
            <div className={`backendLogLine level-${entry.level.toLowerCase()}`} key={entry.sequence}>
              <time>{formatTimestamp(entry.timestamp)}</time>
              <span>{entry.component}</span>
              <b>{entry.level}</b>
              <span>{entry.logger}</span>
              <code>{entry.message}</code>
            </div>
          ))
        ) : (
          <div className="backendLogEmpty">Waiting for matching AES log records...</div>
        )}
      </div>
      <footer>{note || "The stream is bounded to the most recent 1,000 records in this browser."}</footer>
    </section>
  );
}

function deduplicate(entries: BackendLogEntry[]) {
  const bySequence = new Map(entries.map((entry) => [entry.sequence, entry]));
  return [...bySequence.values()].sort((left, right) => left.sequence - right.sequence);
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString();
}
