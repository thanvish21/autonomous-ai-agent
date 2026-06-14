import { useEffect, useRef, useState } from "react";
import { streamTask, getTask, type AgentEvent, type TaskInfo } from "../lib/api";

export function useTaskStream(taskId: string | null) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [task, setTask] = useState<TaskInfo | null>(null);
  const stopRef = useRef<() => void>();

  useEffect(() => {
    stopRef.current?.();
    setEvents([]);
    setTask(null);
    if (!taskId) return;

    let cancelled = false;
    getTask(taskId)
      .then((t) => !cancelled && setTask(t))
      .catch(() => {});

    const stop = streamTask(
      taskId,
      (ev) => {
        setEvents((prev) => [...prev, ev]);
        if (ev.kind === "task_completed" || ev.kind === "task_failed") {
          getTask(taskId)
            .then((t) => !cancelled && setTask(t))
            .catch(() => {});
        }
        if (ev.kind === "human_input_required") {
          getTask(taskId)
            .then((t) => !cancelled && setTask(t))
            .catch(() => {});
        }
      },
      () => {
        // SSE error — leave it; the user can refresh.
      },
    );
    stopRef.current = stop;

    return () => {
      cancelled = true;
      stop();
    };
  }, [taskId]);

  return { events, task, refresh: () => taskId && getTask(taskId).then(setTask).catch(() => {}) };
}
