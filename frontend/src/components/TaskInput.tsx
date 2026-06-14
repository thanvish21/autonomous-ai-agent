import { useState } from "react";

const EXAMPLES = [
  "Research the top 5 Python web frameworks, compare them in a table, and write a 400-word report.",
  "Create a small CSV with 10 fake sales rows, run a Python anomaly check on it, and return findings.",
  "Fetch https://example.com, summarise the page in 3 bullets, and list any outbound links.",
  "Write a Python script that computes the first 20 Fibonacci numbers, run it, and show the output.",
];

interface Props {
  onSubmit: (prompt: string) => Promise<void>;
  disabled?: boolean;
}

export function TaskInput({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  async function send() {
    if (!value.trim() || busy) return;
    setBusy(true);
    try {
      await onSubmit(value.trim());
      setValue("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card task-input">
      <header>
        <h2>New task</h2>
        <span className="hint">Cmd/Ctrl + Enter to submit</span>
      </header>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Describe what you want the agent to do…"
        rows={4}
        disabled={disabled}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") send();
        }}
      />
      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            className="chip"
            type="button"
            disabled={disabled}
            onClick={() => setValue(ex)}
          >
            {ex.length > 70 ? ex.slice(0, 67) + "…" : ex}
          </button>
        ))}
      </div>
      <button
        className="primary"
        onClick={send}
        disabled={disabled || busy || !value.trim()}
      >
        {busy ? "Submitting…" : "Run agent"}
      </button>
    </section>
  );
}
