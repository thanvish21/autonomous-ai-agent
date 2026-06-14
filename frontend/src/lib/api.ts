export type AgentEvent = {
  kind:
    | "task_started"
    | "thought"
    | "tool_call"
    | "tool_result"
    | "human_input_required"
    | "iteration"
    | "final_answer"
    | "task_failed"
    | "task_completed";
  payload: Record<string, unknown>;
  ts: number;
};

export type TaskInfo = {
  id: string;
  prompt: string;
  state:
    | "queued"
    | "running"
    | "awaiting_confirmation"
    | "completed"
    | "failed";
  created_at: number;
  updated_at: number;
  result?: {
    final_answer?: string;
    artifacts?: string[];
    iterations?: number;
  } | null;
  error?: string | null;
  pending_confirmation?: Record<string, unknown> | null;
};

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export async function submitTask(prompt: string): Promise<{ task_id: string }> {
  const res = await fetch(`${API_BASE}/tasks`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) throw new Error(`submit failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function listTasks(): Promise<TaskInfo[]> {
  const res = await fetch(`${API_BASE}/tasks`);
  if (!res.ok) throw new Error("list failed");
  return res.json();
}

export async function getTask(id: string): Promise<TaskInfo> {
  const res = await fetch(`${API_BASE}/tasks/${id}`);
  if (!res.ok) throw new Error("get failed");
  return res.json();
}

export async function getResult(id: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}/tasks/${id}/result`);
  if (!res.ok) throw new Error("result not ready");
  return res.json();
}

export async function confirmAction(
  id: string,
  toolUseId: string,
  approved: boolean,
): Promise<void> {
  await fetch(`${API_BASE}/tasks/${id}/confirm`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tool_use_id: toolUseId, approved }),
  });
}

export function streamTask(
  id: string,
  onEvent: (e: AgentEvent) => void,
  onError?: (err: Event) => void,
): () => void {
  const es = new EventSource(`${API_BASE}/tasks/${id}/stream`);
  es.onmessage = (ev) => {
    try {
      onEvent(JSON.parse(ev.data));
    } catch (err) {
      console.error("bad sse payload", err, ev.data);
    }
  };
  // Server names events by kind; mirror that to onmessage handler.
  const kinds: AgentEvent["kind"][] = [
    "task_started",
    "thought",
    "tool_call",
    "tool_result",
    "human_input_required",
    "iteration",
    "final_answer",
    "task_failed",
    "task_completed",
  ];
  for (const k of kinds) {
    es.addEventListener(k, (ev) => {
      try {
        onEvent(JSON.parse((ev as MessageEvent).data));
      } catch (err) {
        console.error("bad sse payload", err);
      }
    });
  }
  es.onerror = (err) => onError?.(err);
  return () => es.close();
}
