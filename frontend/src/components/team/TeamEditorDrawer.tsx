import { useState, useEffect } from "react";
import {
  useCreateAgent, useUpdateAgent,
  useCreateCrew, useUpdateCrew,
  useCreateTool, useUpdateAgent as _unused,
  useTools,
  useAgents,
  type Agent, type Crew, type Tool,
} from "../../queries/useTeamQuery";
import { useLlmProviders } from "../../queries/useLlmQuery";
import SideDrawer, { DrawerFooter, FormField, inputCls, inputStyle } from "../common/SideDrawer";
import AutoTextarea from "../common/AutoTextarea";

export type EditorTarget =
  | { kind: "agent"; data: Partial<Agent> | null }
  | { kind: "crew"; data: Partial<Crew> | null }
  | { kind: "tool"; data: Partial<Tool> | null };

function titleFor(target: EditorTarget): string {
  const isEdit = !!target.data?.id;
  const noun = target.kind === "agent" ? "Agent" : target.kind === "crew" ? "Crew" : "Tools配置";
  return `${isEdit ? "编辑" : "新建"}${noun}`;
}

function TeamEditorDrawer({
  target,
  onClose,
}: {
  target: EditorTarget | null;
  onClose: () => void;
}) {
  // Force unused import warning to not trigger
  void _unused;

  const open = !!target;
  return (
    <SideDrawer
      title={target ? titleFor(target) : ""}
      open={open}
      onClose={onClose}
      onReset={() => {
        /* reset handled inside forms via remounting; force re-key */
      }}
      footer={undefined}
    >
      {target?.kind === "agent" && (
        <AgentForm key={target.data?.id ?? "new"} data={target.data} onDone={onClose} />
      )}
      {target?.kind === "crew" && (
        <CrewForm key={target.data?.id ?? "new"} data={target.data} onDone={onClose} />
      )}
      {target?.kind === "tool" && (
        <ToolForm key={target.data?.id ?? "new"} data={target.data} onDone={onClose} />
      )}
    </SideDrawer>
  );
}

// ── Process control (Crew 过程控制) ─────────────────────────────────
//
// Segmented control with icons + labels for `Crew.process`. The current
// product only supports sequential (链式) — hierarchical (层式) is
// reserved for a future iteration. We render both options so the UI
// communicates intent, but the 层式 segment is disabled with a "即将
// 开放" tooltip so users don't think it's broken.

function ChainIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.72" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  );
}

function HierarchyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="2" width="6" height="5" rx="1" />
      <rect x="2" y="17" width="6" height="5" rx="1" />
      <rect x="16" y="17" width="6" height="5" rx="1" />
      <path d="M12 7v5" />
      <path d="M5 17v-2a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

function ProcessToggle({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const options: Array<{
    v: string;
    label: string;
    icon: React.ReactNode;
    disabled?: boolean;
    hint?: string;
  }> = [
    { v: "sequential", label: "链式", icon: <ChainIcon /> },
    { v: "hierarchical", label: "层式", icon: <HierarchyIcon />, disabled: true, hint: "即将开放" },
  ];

  return (
    <div
      role="radiogroup"
      aria-label="过程控制"
      className="inline-flex items-stretch rounded-lg p-0.5"
      style={{
        backgroundColor: "var(--color-surface-alt)",
        border: "1px solid var(--color-border-soft)",
      }}
    >
      {options.map((opt) => {
        const selected = value === opt.v;
        return (
          <button
            key={opt.v}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-disabled={opt.disabled}
            tabIndex={selected ? 0 : -1}
            disabled={opt.disabled}
            onClick={() => !opt.disabled && onChange(opt.v)}
            title={opt.disabled ? opt.hint : `切换到${opt.label}`}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed"
            style={{
              backgroundColor: selected ? "var(--color-brand-500)" : "transparent",
              color: selected
                ? "white"
                : opt.disabled
                  ? "var(--color-ink-disabled)"
                  : "var(--color-ink-label)",
              opacity: opt.disabled ? 0.55 : 1,
            }}
          >
            {opt.icon}
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Agent Form ──────────────────────────────────────────────────────

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

  const providerList = (providers as unknown as Array<{ id: string; name: string }>) ?? [];
  const toolList = allTools ?? [];

  const saving = create.isPending || update.isPending;

  async function handleSave() {
    const payload = {
      role,
      goal: goal || null,
      backstory: backstory || null,
      reasoning,
      max_retry: maxRetry,
      memory_enabled: memoryEnabled,
      memory_path: memoryPath || null,
      thinking_mode: thinkingMode,
      tool_ids: toolIds,
      llm_id: llmId || null,
    };
    if (isEdit) {
      await update.mutateAsync({ id: data!.id!, ...payload });
    } else {
      await create.mutateAsync(payload);
    }
    onDone();
  }

  return (
    <>
      <FormField label="角色">
        <input
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className={inputCls}
          style={inputStyle}
        />
      </FormField>
      <FormField label="目标">
        <AutoTextarea
          value={goal ?? ""}
          onChange={(v) => setGoal(v)}
          className={inputCls}
          style={inputStyle}
        />
      </FormField>
      <FormField label="背景">
        <AutoTextarea
          value={backstory ?? ""}
          onChange={(v) => setBackstory(v)}
          className={inputCls}
          style={inputStyle}
        />
      </FormField>

      <div className="mb-4">
        <span className="mb-2 block text-sm" style={{ color: "var(--color-ink-label)" }}>能力</span>
        <div className="ml-12 grid grid-cols-2 gap-y-2 gap-x-6">
          <ToggleRow label="推理" on={reasoning} onChange={setReasoning} />
          <div className="flex items-center gap-2">
            <span className="text-sm" style={{ color: "var(--color-ink-label)" }}>最大尝试次数</span>
            <input
              type="number"
              min={0}
              max={10}
              value={maxRetry}
              onChange={(e) => setMaxRetry(Number(e.target.value))}
              className="w-16 rounded-lg bg-white px-2 py-1 text-sm"
            />
          </div>
          <ToggleRow label="记忆" on={memoryEnabled} onChange={setMemoryEnabled} />
          {memoryEnabled && (
            <input
              value={memoryPath ?? ""}
              onChange={(e) => setMemoryPath(e.target.value)}
              placeholder="记忆路径（可选）"
              className="rounded-lg bg-white px-2 py-1 text-xs"
            />
          )}
          <ToggleRow label="思考" on={thinkingMode} onChange={setThinkingMode} />
        </div>
      </div>

      <FormField label="LLM">
        <select value={llmId ?? ""} onChange={(e) => setLlmId(e.target.value)} className={inputCls} style={inputStyle}>
          <option value="">— 选择 LLM —</option>
          {providerList.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </FormField>

      <FormField label="工具">
        <ToolChips
          toolList={toolList}
          selected={toolIds}
          onChange={setToolIds}
        />
      </FormField>

      <div className="mt-6">
        <DrawerFooter
          onCancel={onDone}
          onSave={handleSave}
          saving={saving}
          saveDisabled={!role.trim()}
        />
      </div>
    </>
  );
}

function ToolChips({
  toolList,
  selected,
  onChange,
}: {
  toolList: Tool[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [adding, setAdding] = useState(false);
  const available = toolList.filter((t) => !selected.includes(t.id));

  return (
    <div className="flex flex-wrap items-center gap-2">
      {selected.map((id) => {
        const t = toolList.find((x) => x.id === id);
        return (
          <span
            key={id}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs"
            style={{
              backgroundColor: "white",
              color: "var(--color-ink-faint)",
            }}
          >
            <button
              onClick={() => onChange(selected.filter((s) => s !== id))}
              className="text-zinc-400 hover:text-red-500"
            >
              ×
            </button>
            {t?.name ?? id}
          </span>
        );
      })}
      <button
        onClick={() => setAdding((v) => !v)}
        className="flex h-7 w-7 items-center justify-center rounded-lg bg-white"
        style={{ color: "var(--color-ink-muted)" }}
        title="添加工具"
      >
        +
      </button>
      {adding && (
        <select
          onChange={(e) => {
            if (e.target.value) {
              onChange([...selected, e.target.value]);
              setAdding(false);
            }
          }}
          className="rounded-md bg-white px-2 py-1 text-xs"
          defaultValue=""
        >
          <option value="">— 选择 —</option>
          {available.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

function ToggleRow({
  label,
  on,
  onChange,
}: {
  label: string;
  on: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-sm" style={{ color: "var(--color-ink-label)" }}>· {label}</span>
      <button
        onClick={() => onChange(!on)}
        className="relative inline-flex h-5 w-9 items-center rounded-full"
        style={{ backgroundColor: on ? "#10b981" : "#cbd5e1" }}
      >
        <span
          className="absolute h-4 w-4 rounded-full bg-white shadow-sm transition-transform"
          style={{ transform: on ? "translateX(18px)" : "translateX(2px)" }}
        />
      </button>
    </div>
  );
}

// ── Crew Form ───────────────────────────────────────────────────────

function CrewForm({ data, onDone }: { data: Partial<Crew> | null; onDone: () => void }) {
  const isEdit = !!data?.id;
  const create = useCreateCrew();
  const update = useUpdateCrew();
  const { data: agents } = useAgents();

  const [name, setName] = useState(data?.name ?? "");
  const [process, setProcess] = useState(data?.process ?? "sequential");
  const [agentIds, setAgentIds] = useState<string[]>(data?.agent_ids ?? []);

  const agentList = agents ?? [];
  const saving = create.isPending || update.isPending;

  async function handleSave() {
    const payload = { name, process, agent_ids: agentIds };
    if (isEdit) await update.mutateAsync({ id: data!.id!, ...payload });
    else await create.mutateAsync(payload);
    onDone();
  }

  const available = agentList.filter((a) => !agentIds.includes(a.id));

  return (
    <>
      <FormField label="队名">
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} style={inputStyle} />
      </FormField>

      <FormField label="过程控制">
        <ProcessToggle value={process} onChange={setProcess} />
      </FormField>

      <FormField label="角色">
        <div className="flex flex-wrap items-center gap-2">
          {agentIds.map((id) => {
            const a = agentList.find((x) => x.id === id);
            return (
              <span
                key={id}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs"
                style={{ backgroundColor: "white", color: "var(--color-ink-faint)" }}
              >
                <button
                  onClick={() => setAgentIds(agentIds.filter((s) => s !== id))}
                  className="text-zinc-400 hover:text-red-500"
                >
                  ×
                </button>
                {a?.role ?? id}
              </span>
            );
          })}
          {available.length > 0 && (
            <select
              onChange={(e) => {
                if (e.target.value) {
                  setAgentIds([...agentIds, e.target.value]);
                  e.target.value = "";
                }
              }}
              className="rounded-md bg-white px-2 py-1 text-xs"
              defaultValue=""
            >
              <option value="">+ 添加</option>
              {available.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.role}
                </option>
              ))}
            </select>
          )}
        </div>
      </FormField>

      <div className="mt-6">
        <DrawerFooter
          onCancel={onDone}
          onSave={handleSave}
          saving={saving}
          saveDisabled={!name.trim()}
        />
      </div>
    </>
  );
}

// ── Tool Form ───────────────────────────────────────────────────────

function ToolForm({ data, onDone }: { data: Partial<Tool> | null; onDone: () => void }) {
  const create = useCreateTool();
  const [name, setName] = useState(data?.name ?? "");
  const [scriptPath, setScriptPath] = useState(data?.script_path ?? "");

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  useEffect(() => {}, []);

  async function handleSave() {
    await create.mutateAsync({
      name,
      script_path: scriptPath || null,
      source: "user",
    });
    onDone();
  }

  return (
    <>
      <div
        className="mb-4 rounded-lg bg-white p-3 text-xs leading-relaxed"
        style={{ color: "var(--color-ink-faint)" }}
      >
        建议将脚本文件夹统一放置在 MyCrew 根目录/src/tools 文件夹中，系统将自动扫描并加载。
      </div>

      <FormField label="名称">
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} style={inputStyle} />
      </FormField>

      <FormField label="路径">
        <div className="flex items-center gap-2">
          <input
            value={scriptPath ?? ""}
            onChange={(e) => setScriptPath(e.target.value)}
            style={inputStyle}
            className={inputCls}
            placeholder="src/tools/my_tool.py"
          />
          <button
            className="rounded-lg bg-white p-2"
            style={{ color: "var(--color-ink-muted)" }}
            title="选择文件夹"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
          </button>
        </div>
      </FormField>

      <div className="mt-6">
        <DrawerFooter
          onCancel={onDone}
          onSave={handleSave}
          saving={create.isPending}
          saveDisabled={!name.trim()}
        />
      </div>
    </>
  );
}

export default TeamEditorDrawer;
