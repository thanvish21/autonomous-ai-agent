import { useCallback, useEffect, useState } from "react";
import { TaskInput } from "./components/TaskInput";
import { ExecutionTrace } from "./components/ExecutionTrace";
import { OutputRenderer } from "./components/OutputRenderer";
import { TaskHistory } from "./components/TaskHistory";
import { useTaskStream } from "./hooks/useTaskStream";
import { confirmAction, listTasks, submitTask, type TaskInfo } from "./lib/api";

export default function App() {
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const { events, task, refresh } = useTaskStream(activeId);

  const refreshTasks = useCallback(async () => {
    try {
      setTasks(await listTasks());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refreshTasks();
    const id = setInterval(refreshTasks, 5000);
    return () => clearInterval(id);
  }, [refreshTasks]);

  const handleSubmit = async (prompt: string) => {
    const { task_id } = await submitTask(prompt);
    setActiveId(task_id);
    await refreshTasks();
  };

  const pending = (task?.pending_confirmation as Record<string, unknown> | null) || null;
  const pendingToolUseId =
    pending && typeof pending.key === "string" ? (pending.key as string) : null;

  const handleConfirm = async (toolUseId: string, approved: boolean) => {
    if (!activeId) return;
    await confirmAction(activeId, toolUseId, approved);
    await refresh();
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="logo" />
          <span>Autonomous Agent</span>
        </div>
        <a
          className="ghost"
          href="https://github.com/anthropics/anthropic-sdk-python"
          target="_blank"
          rel="noreferrer"
        >
          Built with Claude tool use
        </a>
      </header>

      <main className="grid">
        <aside>
          <TaskHistory
            tasks={tasks}
            selectedId={activeId}
            onSelect={setActiveId}
            onRefresh={refreshTasks}
          />
        </aside>
        <section className="main-col">
          <TaskInput onSubmit={handleSubmit} />
          <ExecutionTrace
            events={events}
            onConfirm={handleConfirm}
            pendingToolUseId={pendingToolUseId}
          />
        </section>
        <aside>
          <OutputRenderer task={task} />
        </aside>
      </main>

      <footer className="app-footer">
        <span>SSE-streamed reasoning · LangGraph orchestration · ChromaDB memory</span>
      </footer>
    </div>
  );
}
