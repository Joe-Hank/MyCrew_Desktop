import { useState } from "react";
import AgentList from "../components/team/AgentList";
import CrewList from "../components/team/CrewList";
import ToolList from "../components/team/ToolList";
import EditorDrawer, { type EditorTarget } from "../components/team/EditorDrawer";
import { useAgents, useCrews, useTools, type Agent, type Crew } from "../queries/useTeamQuery";

type Tab = "agent" | "crew" | "tool";

function TeamPage() {
  const [tab, setTab] = useState<Tab>("agent");
  const [editor, setEditor] = useState<EditorTarget | null>(null);

  const { data: agents = [] } = useAgents();
  const { data: crews = [] } = useCrews();
  const { data: tools = [] } = useTools();

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "agent", label: "Agent", count: agents.length },
    { key: "crew", label: "Crew", count: crews.length },
    { key: "tool", label: "Tool", count: tools.length },
  ];

  function handleNewAgent() {
    setEditor({ kind: "agent", data: null });
  }
  function handleEditAgent(agent: Agent) {
    setEditor({ kind: "agent", data: agent });
  }
  function handleNewCrew() {
    setEditor({ kind: "crew", data: null });
  }
  function handleEditCrew(crew: Crew) {
    setEditor({ kind: "crew", data: crew });
  }
  function handleNewTool() {
    setEditor({ kind: "tool", data: null });
  }

  function handleNew() {
    if (tab === "agent") handleNewAgent();
    else if (tab === "crew") handleNewCrew();
    else handleNewTool();
  }

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar + new button */}
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 dark:border-zinc-800">
        <div className="flex items-center gap-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => {
                setTab(t.key);
                setEditor(null);
              }}
              className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium transition-colors ${
                tab === t.key
                  ? "border-b-2 border-blue-500 text-blue-600 dark:text-blue-400"
                  : "text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
            >
              {t.label}
              <span className="rounded-full bg-zinc-200 px-1.5 py-0.5 text-xs dark:bg-zinc-700">
                {t.count}
              </span>
            </button>
          ))}
        </div>

        <button
          onClick={handleNew}
          className="rounded bg-blue-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-600"
        >
          + 新建
        </button>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        <div className={`flex-1 overflow-auto ${editor ? "border-r border-zinc-200 dark:border-zinc-700" : ""}`}>
          {tab === "agent" && <AgentList onEdit={handleEditAgent} onNew={handleNewAgent} />}
          {tab === "crew" && <CrewList onEdit={handleEditCrew} onNew={handleNewCrew} />}
          {tab === "tool" && <ToolList onNew={handleNewTool} />}
        </div>

        {editor && (
          <div className="w-[320px] shrink-0">
            <EditorDrawer target={editor} onClose={() => setEditor(null)} />
          </div>
        )}
      </div>
    </div>
  );
}

export default TeamPage;
