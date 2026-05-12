import { useState } from "react";
import {
  useAgents,
  useCrews,
  useTools,
  type Agent,
  type Crew,
  type Tool,
} from "../queries/useTeamQuery";
import { usePrefsStore, type TeamTab } from "../stores/usePrefsStore";
import PillTabs from "../components/common/PillTabs";
import AgentsTable from "../components/team/AgentsTable";
import CrewsTable from "../components/team/CrewsTable";
import ToolsTable from "../components/team/ToolsTable";
import TeamEditorDrawer, { type EditorTarget } from "../components/team/TeamEditorDrawer";

type Tab = TeamTab;

function TeamPage() {
  const activeTab = usePrefsStore((s) => s.teamActiveTab);
  const setActiveTab = usePrefsStore((s) => s.setTeamActiveTab);
  const [editor, setEditor] = useState<EditorTarget | null>(null);

  const { data: agents } = useAgents();
  const { data: crews } = useCrews();
  const { data: tools } = useTools();

  const tabs = [
    { key: "agents" as const, label: "Agents", count: agents?.length ?? 0 },
    { key: "crews" as const, label: "Crews", count: crews?.length ?? 0 },
    { key: "tools" as const, label: "Tools", count: tools?.length ?? 0 },
  ];

  function openNew() {
    if (activeTab === "agents") setEditor({ kind: "agent", data: null });
    else if (activeTab === "crews") setEditor({ kind: "crew", data: null });
    else setEditor({ kind: "tool", data: null });
  }

  function editAgent(a: Agent) {
    setEditor({ kind: "agent", data: a });
  }
  function editCrew(c: Crew) {
    setEditor({ kind: "crew", data: c });
  }
  function editTool(t: Tool) {
    setEditor({ kind: "tool", data: t });
  }

  const newButtonLabel =
    activeTab === "agents" ? "新建员工" : activeTab === "crews" ? "新建Crew" : "Tools配置";

  return (
    <div className="flex h-full flex-col px-6 pb-4 pt-4">
      {/* Tab bar */}
      <div className="mb-4 flex items-center justify-between">
        <PillTabs<Tab> tabs={tabs} active={activeTab} onChange={setActiveTab} />

        <button
          onClick={openNew}
          className="flex items-center gap-1 rounded-2xl px-5 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90"
          style={{ backgroundColor: "var(--color-brand-500)" }}
        >
          <span>{newButtonLabel}</span>
          <span className="text-base">+</span>
        </button>
      </div>

      {/* Table area */}
      <div className="min-h-0 flex-1 overflow-auto">
        {activeTab === "agents" && <AgentsTable onEdit={editAgent} />}
        {activeTab === "crews" && <CrewsTable onEdit={editCrew} />}
        {activeTab === "tools" && <ToolsTable onEdit={editTool} />}
      </div>

      {/* Editor drawer */}
      <TeamEditorDrawer target={editor} onClose={() => setEditor(null)} />
    </div>
  );
}

export default TeamPage;
