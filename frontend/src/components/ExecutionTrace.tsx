import { useEffect, useRef } from "react";
import type { AgentEvent } from "../lib/api";

interface Props {
  events: AgentEvent[];
  onConfirm?: (toolUseId: string, approved: boolean) => void;
  pendingToolUseId?: string | null;
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + " …" : s;
}

export function ExecutionTrace({ events, onConfirm, pendingToolUseId }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <section className="card trace empty">
        <p>No task running. Submit a task above to see the agent's trace stream here.</p>
      </section>
    );
  }

  return (
    <section className="card trace">
      <header>
        <h2>Execution trace</h2>
        <span className="hint">{events.length} events</span>
      </header>
      <ol className="trace-list">
        {events.map((ev, i) => (
          <li key={i} className={`trace-row trace-${ev.kind}`}>
            <div className="kind">{ev.kind}</div>
            <div className="body">{renderBody(ev, onConfirm, pendingToolUseId)}</div>
          </li>
        ))}
        <div ref={endRef} />
      </ol>
    </section>
  );
}

function renderBody(
  ev: AgentEvent,
  onConfirm?: (id: string, ok: boolean) => void,
  pendingToolUseId?: string | null,
) {
  const p = ev.payload as Record<string, any>;
  switch (ev.kind) {
    case "task_started":
      return (
        <div>
          <strong>Goal:</strong> {String(p.prompt ?? "")}
          {p.recalls ? <span className="muted"> · recalled {p.recalls} prior task(s)</span> : null}
        </div>
      );
    case "iteration":
      return (
        <div className="muted">
          Iteration {p.n}/{p.max}
        </div>
      );
    case "thought":
      return <div className="thought">{String(p.text ?? "")}</div>;
    case "tool_call":
      return (
        <div>
          <strong>{String(p.name)}</strong>
          <pre>{truncate(fmt(p.input), 1200)}</pre>
        </div>
      );
    case "tool_result":
      return (
        <div className={p.ok ? "ok" : "err"}>
          <strong>{String(p.name)}</strong> · {p.ok ? "ok" : "error"}
          {p.error ? <div className="error-msg">{String(p.error)}</div> : null}
          {p.data !== undefined ? (
            <pre>{truncate(fmt(p.data), 1500)}</pre>
          ) : null}
        </div>
      );
    case "human_input_required": {
      const toolUseId = String(p.tool_use_id ?? "");
      const isThisOne = pendingToolUseId && pendingToolUseId === toolUseId;
      return (
        <div className="confirm">
          <div>
            <strong>Confirm {String(p.tool)}:</strong>
            <pre>{truncate(fmt(p.args), 800)}</pre>
          </div>
          {isThisOne ? (
            <div className="confirm-buttons">
              <button
                className="primary"
                onClick={() => onConfirm?.(toolUseId, true)}
              >
                Approve
              </button>
              <button onClick={() => onConfirm?.(toolUseId, false)}>Reject</button>
            </div>
          ) : (
            <div className="muted">Resolved.</div>
          )}
        </div>
      );
    }
    case "task_completed":
      return (
        <div className="ok">
          Done in {String(p.iterations ?? "?")} iteration(s).
          {p.artifacts && (p.artifacts as string[]).length > 0 ? (
            <div className="muted">
              Artifacts: {(p.artifacts as string[]).join(", ")}
            </div>
          ) : null}
        </div>
      );
    case "task_failed":
      return <div className="err">Failed: {String(p.error)}</div>;
    default:
      return <pre>{fmt(p)}</pre>;
  }
}
