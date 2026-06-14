import type { TaskInfo } from "../lib/api";

interface Props {
  tasks: TaskInfo[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}

function rel(ts: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function TaskHistory({ tasks, selectedId, onSelect, onRefresh }: Props) {
  return (
    <section className="card history">
      <header>
        <h2>History</h2>
        <button className="ghost" onClick={onRefresh} title="Refresh">
          ↻
        </button>
      </header>
      {tasks.length === 0 ? (
        <p className="muted">No tasks yet.</p>
      ) : (
        <ul className="history-list">
          {tasks.map((t) => (
            <li
              key={t.id}
              className={t.id === selectedId ? "active" : ""}
              onClick={() => onSelect(t.id)}
            >
              <div className="prompt">{t.prompt.slice(0, 80)}{t.prompt.length > 80 ? "…" : ""}</div>
              <div className="meta">
                <span className={`badge state-${t.state}`}>{t.state}</span>
                <span className="muted">{rel(t.created_at)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
