import { useState } from "react";
import {
  useCreateAgent, useUpdateAgent,
  useCreateCrew, useUpdateCrew,
  useCreateTool,
  useTools,
  useAgents,
  type Agent, type Crew, type Tool,
} from "../../queries/useTeamQuery";
import { useLlmProviders } from "../../queries/useLlmQuery";

export type EditorTarget =
  | { kind: "agent"; data: Partial<Agent> | null }
  | { kind: "crew"; data: Partial<Crew> | null }
  | { kind: "tool"; data: Partial<Tool> | null };

function EditorDrawer({
  target,
  onClose,
}: {
  target: EditorTarget;
  onClose: () => void;
}) {
  return (
    <div className="flex h-full flex-col border-l border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700">
        <span className="text-xs font-semibold">
          {target.data?.id ? "编辑" : "新建"}{" "}
          {target.kind === "agent" ? "Agent" : target.kind === "crew" ? "Crew" : "Tool"}
        </span>
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200">
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {target.kind === "agent" && <AgentForm data={target.data} onDone={onClose} />}
        {target.kind === "crew" && <CrewForm data={target.data} onDone={onClose} />}
        {target.kind === "tool" && <ToolForm data={target.data} onDone={onClose} />}
      </div>
    </div>
  );
}

// --- Agent Form ---

function AgentForm({ data, onDone }: { data: Partial<Agent> | null; onDone: () => void }) {
  const isEdit = !!data?.id;
  const create = useCreateAgent();
  const update = useUpdateAgent();
  const { data: providers } = useLlmProviders();
  const { data: allTools } = useTools();

  const [role, setRole] = useState(data?.role ?? "");
  const [goal, setGoal] = useState(data?.goal ?? "");
  const [backstory, setBackstory] = useState(data?.backstory ?? "");
  const [reasoning, setReasoning] = useState(data?.reasoning ?? false);
  const [maxRetry, setMaxRetry] = useState(data?.max_retry ?? 3);
  const [memoryEnabled, setMemoryEnabled] = useState(data?.memory_enabled ?? false);
  const [memoryPath, setMemoryPath] = useState(data?.memory_path ?? "");
  const [thinkingMode, setThinkingMode] = useState(data?.thinking_mode ?? false);
  const [toolIds, setToolIds] = useState<string[]>(data?.tool_ids ?? []);
  const [llmId, setLlmId] = useState(data?.llm_id ?? "");

  const providerList = (providers as unknown as Array<Record<string, unknown>>) ?? [];
  const toolList = allTools ?? [];

  async function handleSave() {
    const payload = {
      role, goal: goal || null, backstory: backstory || null,
      reasoning, max_retry: maxRetry, memory_enabled: memoryEnabled,
      memory_path: memoryPath || null, thinking_mode: thinkingMode,
      tool_ids: toolIds, llm_id: llmId || null,
    };
    if (isEdit) {
      await update.mutateAsync({ id: data!.id!, ...payload });
    } else {
      await create.mutateAsync(payload);
    }
    onDone();
  }

  return (
    <div className="space-y-3">
      <Field label="角色名称">
        <input value={role} onChange={(e) => setRole(e.target.value)} className={inputCls} />
      </Field>
      <Field label="目标">
        <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={2} className={inputCls} />
      </Field>
      <Field label="背景故事">
        <textarea value={backstory} onChange={(e) => setBackstory(e.target.value)} rows={2} className={inputCls} />
      </Field>
      <Field label="LLM">
        <select value={llmId} onChange={(e) => setLlmId(e.target.value)} className={inputCls}>
          <option value="">选择 LLM...</option>
          {providerList.map((p) => (
            <option key={p.id as string} value={p.id as string}>{p.name as string}</option>
          ))}
        </select>
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Checkbox label="推理模式" checked={reasoning} onChange={setReasoning} />
        <Checkbox label="思考模式" checked={thinkingMode} onChange={setThinkingMode} />
        <Checkbox label="启用记忆" checked={memoryEnabled} onChange={setMemoryEnabled} />
        <Field label="最大重试">
          <input
            type="number" min={0} max={10}
            value={maxRetry} onChange={(e) => setMaxRetry(Number(e.target.value))}
            className={inputCls}
          />
        </Field>
      </div>

      {memoryEnabled && (
        <Field label="记忆路径">
          <input value={memoryPath} onChange={(e) => setMemoryPath(e.target.value)} className={inputCls} placeholder="可选" />
        </Field>
      )}

      <Field label="工具">
        <div className="max-h-32 space-y-1 overflow-auto rounded border border-zinc-200 p-2 dark:border-zinc-700">
          {toolList.length === 0 && <span className="text-[10px] text-zinc-400">暂无工具</span>}
          {toolList.map((t) => (
            <label key={t.id} className="flex items-center gap-1.5 text-[11px]">
              <input
                type="checkbox"
                checked={toolIds.includes(t.id)}
                onChange={(e) => {
                  if (e.target.checked) setToolIds([...toolIds, t.id]);
                  else setToolIds(toolIds.filter((x) => x !== t.id));
                }}
                className="h-3 w-3"
              />
              {t.name}
            </label>
          ))}
        </div>
      </Field>

      <button
        onClick={handleSave}
        disabled={!role.trim() || create.isPending || update.isPending}
        className="w-full rounded bg-blue-500 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending || update.isPending ? "保存中..." : "保存"}
      </button>
    </div>
  );
}

// --- Crew Form ---

function CrewForm({ data, onDone }: { data: Partial<Crew> | null; onDone: () => void }) {
  const isEdit = !!data?.id;
  const create = useCreateCrew();
  const update = useUpdateCrew();
  const { data: agents } = useAgents();

  const [name, setName] = useState(data?.name ?? "");
  const [process, setProcess] = useState(data?.process ?? "sequential");
  const [agentIds, setAgentIds] = useState<string[]>(data?.agent_ids ?? []);

  const agentList = agents ?? [];

  async function handleSave() {
    const payload = { name, process, agent_ids: agentIds };
    if (isEdit) {
      await update.mutateAsync({ id: data!.id!, ...payload });
    } else {
      await create.mutateAsync(payload);
    }
    onDone();
  }

  return (
    <div className="space-y-3">
      <Field label="团队名称">
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
      </Field>
      <Field label="执行模式">
        <select value={process} onChange={(e) => setProcess(e.target.value)} className={inputCls}>
          <option value="sequential">顺序 (Sequential)</option>
          <option value="hierarchical">层级 (Hierarchical) — 实验性</option>
        </select>
      </Field>
      <Field label="成员 Agents">
        <div className="max-h-32 space-y-1 overflow-auto rounded border border-zinc-200 p-2 dark:border-zinc-700">
          {agentList.length === 0 && <span className="text-[10px] text-zinc-400">暂无 Agent</span>}
          {agentList.map((a) => (
            <label key={a.id} className="flex items-center gap-1.5 text-[11px]">
              <input
                type="checkbox"
                checked={agentIds.includes(a.id)}
                onChange={(e) => {
                  if (e.target.checked) setAgentIds([...agentIds, a.id]);
                  else setAgentIds(agentIds.filter((x) => x !== a.id));
                }}
                className="h-3 w-3"
              />
              {a.role}
            </label>
          ))}
        </div>
      </Field>

      <button
        onClick={handleSave}
        disabled={!name.trim() || create.isPending || update.isPending}
        className="w-full rounded bg-blue-500 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending || update.isPending ? "保存中..." : "保存"}
      </button>
    </div>
  );
}

// --- Tool Form ---

function ToolForm({ data, onDone }: { data: Partial<Tool> | null; onDone: () => void }) {
  const create = useCreateTool();
  const [name, setName] = useState(data?.name ?? "");
  const [scriptPath, setScriptPath] = useState(data?.script_path ?? "");
  const [source, setSource] = useState(data?.source ?? "user");

  async function handleSave() {
    await create.mutateAsync({
      name,
      script_path: scriptPath || null,
      source,
    });
    onDone();
  }

  return (
    <div className="space-y-3">
      <p className="rounded bg-zinc-50 p-2 text-[10px] text-zinc-500 dark:bg-zinc-800">
        建议将脚本放在项目根目录的 src/tools/ 下，也可使用"扫描"自动发现。
      </p>
      <Field label="名称">
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
      </Field>
      <Field label="脚本路径">
        <input value={scriptPath} onChange={(e) => setScriptPath(e.target.value)} className={inputCls} placeholder="src/tools/my_tool.py" />
      </Field>
      <Field label="来源">
        <select value={source} onChange={(e) => setSource(e.target.value)} className={inputCls}>
          <option value="user">用户</option>
          <option value="builtin">内置</option>
        </select>
      </Field>

      <button
        onClick={handleSave}
        disabled={!name.trim() || create.isPending}
        className="w-full rounded bg-blue-500 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending ? "保存中..." : "保存"}
      </button>
    </div>
  );
}

// --- Shared helpers ---

const inputCls =
  "w-full rounded border border-zinc-300 px-2.5 py-1.5 text-xs dark:border-zinc-600 dark:bg-zinc-800";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] text-zinc-500">{label}</label>
      {children}
    </div>
  );
}

function Checkbox({
  label, checked, onChange,
}: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-1.5 text-[11px]">
      <input
        type="checkbox" checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3 w-3"
      />
      {label}
    </label>
  );
}

export default EditorDrawer;
