import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TaskInfo } from "../lib/api";

interface Props {
  task: TaskInfo | null;
}

export function OutputRenderer({ task }: Props) {
  if (!task) {
    return (
      <section className="card output empty">
        <h2>Final output</h2>
        <p>Run a task to see the agent's final answer here.</p>
      </section>
    );
  }

  const answer = task.result?.final_answer ?? "";
  const artifacts = task.result?.artifacts ?? [];

  return (
    <section className="card output">
      <header>
        <h2>Final output</h2>
        <span className={`badge state-${task.state}`}>{task.state}</span>
      </header>

      {task.error ? (
        <div className="error-msg">Error: {task.error}</div>
      ) : null}

      {answer ? (
        <div className="markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
        </div>
      ) : (
        <p className="muted">No final answer yet…</p>
      )}

      {artifacts.length > 0 ? (
        <div className="artifacts">
          <h3>Artifacts</h3>
          <ul>
            {artifacts.map((a) => (
              <li key={a}>
                <code>{a}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
