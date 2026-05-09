import { useState } from "react";
import {
  useCreateLlmProvider,
  useUpdateLlmProvider,
  useDeleteLlmProvider,
  useCreateLlmModel,
  useUpdateLlmModel,
  useDeleteLlmModel,
  LLM_TYPES,
  type LlmProvider,
  type LlmModel,
} from "../../queries/useLlmQuery";
import {
  useCreateMcpServer,
  useUpdateMcpServer,
  useDeleteMcpServer,
} from "../../queries/useMcpQuery";

export type SettingsEditorTarget =
  | { kind: "llm"; data: Partial<LlmProvider> | null }
  | { kind: "mcp"; data: Record<string, unknown> | null };

function EditorDrawer({
  target,
  onClose,
}: {
  target: SettingsEditorTarget;
  onClose: () => void;
}) {
  return (
    <div className="flex h-full flex-col border-l border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700">
        <span className="text-xs font-semibold">
          {target.data?.id ? "编辑" : "新建"}{" "}
          {target.kind === "llm" ? "LLM 提供商" : "MCP 服务器"}
        </span>
        <button
          onClick={onClose}
          className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {target.kind === "llm" && (
          <LlmForm data={target.data as Partial<LlmProvider> | null} onDone={onClose} />
        )}
        {target.kind === "mcp" && (
          <McpForm data={target.data} onDone={onClose} />
        )}
      </div>
    </div>
  );
}

// --- LLM Form ---

function LlmForm({
  data,
  onDone,
}: {
  data: Partial<LlmProvider> | null;
  onDone: () => void;
}) {
  const isEdit = !!data?.id;
  const create = useCreateLlmProvider();
  const update = useUpdateLlmProvider();
  const del = useDeleteLlmProvider();
  const createModel = useCreateLlmModel();
  const updateModel = useUpdateLlmModel();
  const deleteModel = useDeleteLlmModel();

  const [name, setName] = useState(data?.name ?? "");
  const [type, setType] = useState(data?.type ?? "openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(data?.base_url ?? "");

  // Inline model editor state
  const existingModels = (data?.models ?? []) as LlmModel[];
  const [newModelName, setNewModelName] = useState("");
  const [newModelLabel, setNewModelLabel] = useState("");
  const [newModelMaxTokens, setNewModelMaxTokens] = useState(4096);
  const [newModelThinking, setNewModelThinking] = useState(false);

  const needsBaseUrl = type === "custom" || type === "ollama";

  async function handleSave() {
    const payload: Record<string, unknown> = {
      name,
      type,
      base_url: baseUrl || null,
    };
    if (apiKey) {
      payload.api_key_ref = apiKey;
    }
    if (isEdit) {
      await update.mutateAsync({ id: data!.id!, ...payload });
    } else {
      await create.mutateAsync(payload as { name: string; type: string; api_key_ref?: string; base_url?: string });
    }
    onDone();
  }

  async function handleDelete() {
    if (!data?.id) return;
    if (!confirm("确定删除此 LLM 提供商？关联的模型也会被删除。")) return;
    await del.mutateAsync(data.id);
    onDone();
  }

  async function handleAddModel() {
    if (!data?.id || !newModelName.trim()) return;
    await createModel.mutateAsync({
      provider_id: data.id,
      model_name: newModelName,
      label: newModelLabel || undefined,
      max_tokens: newModelMaxTokens || undefined,
      supports_thinking: newModelThinking,
    });
    setNewModelName("");
    setNewModelLabel("");
    setNewModelMaxTokens(4096);
    setNewModelThinking(false);
  }

  async function handleDeleteModel(modelId: string) {
    await deleteModel.mutateAsync(modelId);
  }

  async function handleToggleThinking(model: LlmModel) {
    await updateModel.mutateAsync({
      id: model.id,
      supports_thinking: !model.supports_thinking,
    });
  }

  return (
    <div className="space-y-3">
      <Field label="名称">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={inputCls}
          placeholder="如：My OpenAI"
        />
      </Field>

      <Field label="类型">
        <select value={type} onChange={(e) => setType(e.target.value)} className={inputCls}>
          {LLM_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </Field>

      <Field label="API Key">
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className={inputCls}
          placeholder={isEdit ? "已设置，留空保留" : "sk-..."}
        />
      </Field>

      <Field label={`Base URL${needsBaseUrl ? " (必填)" : " (可选，代理转发)"}`}>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          className={inputCls}
          placeholder={
            type === "ollama"
              ? "http://localhost:11434/v1"
              : "https://api.openai.com/v1"
          }
        />
      </Field>

      <button
        onClick={handleSave}
        disabled={!name.trim() || (needsBaseUrl && !baseUrl.trim()) || create.isPending || update.isPending}
        className="w-full rounded bg-blue-500 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending || update.isPending ? "保存中..." : "保存"}
      </button>

      {isEdit && (
        <button
          onClick={handleDelete}
          disabled={del.isPending}
          className="w-full rounded border border-red-300 py-2 text-xs font-medium text-red-500 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
        >
          删除提供商
        </button>
      )}

      {/* Model list (only for existing providers) */}
      {isEdit && (
        <div className="mt-4 border-t border-zinc-200 pt-3 dark:border-zinc-700">
          <h4 className="mb-2 text-[11px] font-semibold text-zinc-600 dark:text-zinc-400">
            模型列表
          </h4>

          {existingModels.length === 0 && (
            <p className="text-[10px] text-zinc-400">暂无模型，请在下方添加</p>
          )}

          <div className="space-y-1.5">
            {existingModels.map((m) => (
              <div
                key={m.id}
                className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1.5 dark:border-zinc-700"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[11px] font-medium">{m.model_name}</div>
                  <div className="flex items-center gap-2 text-[10px] text-zinc-400">
                    {m.label && <span>{m.label}</span>}
                    {m.max_tokens && <span>{m.max_tokens} tokens</span>}
                    <button
                      onClick={() => handleToggleThinking(m)}
                      className={`rounded px-1 ${
                        m.supports_thinking
                          ? "bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400"
                          : "bg-zinc-100 text-zinc-400 dark:bg-zinc-800"
                      }`}
                    >
                      {m.supports_thinking ? "🧠 思考" : "思考"}
                    </button>
                  </div>
                </div>
                <button
                  onClick={() => handleDeleteModel(m.id)}
                  className="ml-2 text-[10px] text-zinc-400 hover:text-red-500"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>

          {/* Add model form */}
          <div className="mt-2 space-y-1.5 rounded border border-dashed border-zinc-300 p-2 dark:border-zinc-600">
            <div className="grid grid-cols-2 gap-1.5">
              <input
                value={newModelName}
                onChange={(e) => setNewModelName(e.target.value)}
                className={inputSmCls}
                placeholder="模型名 (如 gpt-4o)"
              />
              <input
                value={newModelLabel}
                onChange={(e) => setNewModelLabel(e.target.value)}
                className={inputSmCls}
                placeholder="显示标签 (可选)"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <input
                type="number"
                value={newModelMaxTokens}
                onChange={(e) => setNewModelMaxTokens(Number(e.target.value))}
                className={`${inputSmCls} w-24`}
                placeholder="max tokens"
              />
              <label className="flex items-center gap-1 text-[10px]">
                <input
                  type="checkbox"
                  checked={newModelThinking}
                  onChange={(e) => setNewModelThinking(e.target.checked)}
                  className="h-3 w-3"
                />
                思考模式
              </label>
              <button
                onClick={handleAddModel}
                disabled={!newModelName.trim() || createModel.isPending}
                className="ml-auto rounded bg-zinc-200 px-2 py-0.5 text-[10px] font-medium hover:bg-zinc-300 disabled:opacity-50 dark:bg-zinc-700 dark:hover:bg-zinc-600"
              >
                + 添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// --- MCP Form ---

function McpForm({
  data,
  onDone,
}: {
  data: Record<string, unknown> | null;
  onDone: () => void;
}) {
  const isEdit = !!data?.id;
  const create = useCreateMcpServer();
  const update = useUpdateMcpServer();
  const del = useDeleteMcpServer();

  const [name, setName] = useState((data?.name as string) ?? "");
  const [transport, setTransport] = useState((data?.transport as string) ?? "stdio");
  const [command, setCommand] = useState((data?.command as string) ?? "");
  const [args, setArgs] = useState<string[]>((data?.args as string[]) ?? []);
  const [url, setUrl] = useState((data?.url as string) ?? "");
  const [envRef, setEnvRef] = useState<Record<string, string>>(
    (data?.env_ref as Record<string, string>) ?? {}
  );
  const [enabled, setEnabled] = useState((data?.enabled as boolean) ?? true);
  const [autoStart, setAutoStart] = useState((data?.auto_start as boolean) ?? true);
  const [timeout, setTimeout_] = useState((data?.timeout as number) ?? 30);

  // Dynamic args editor
  const [newArg, setNewArg] = useState("");
  // Dynamic env editor
  const [newEnvKey, setNewEnvKey] = useState("");
  const [newEnvVal, setNewEnvVal] = useState("");

  async function handleSave() {
    const payload: Record<string, unknown> = {
      name,
      transport,
      enabled,
      auto_start: autoStart,
      timeout,
    };
    if (transport === "stdio") {
      payload.command = command;
      payload.args = args;
      payload.env_ref = envRef;
    } else {
      payload.url = url;
    }

    if (isEdit) {
      await update.mutateAsync({ id: data!.id as string, ...payload });
    } else {
      await create.mutateAsync(payload);
    }
    onDone();
  }

  async function handleDelete() {
    if (!data?.id) return;
    if (!confirm("确定删除此 MCP 服务器？")) return;
    await del.mutateAsync(data.id as string);
    onDone();
  }

  function addArg() {
    if (!newArg.trim()) return;
    setArgs([...args, newArg]);
    setNewArg("");
  }

  function removeArg(idx: number) {
    setArgs(args.filter((_, i) => i !== idx));
  }

  function addEnv() {
    if (!newEnvKey.trim()) return;
    setEnvRef({ ...envRef, [newEnvKey]: newEnvVal });
    setNewEnvKey("");
    setNewEnvVal("");
  }

  function removeEnv(key: string) {
    const next = { ...envRef };
    delete next[key];
    setEnvRef(next);
  }

  return (
    <div className="space-y-3">
      <Field label="名称">
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="如：filesystem" />
      </Field>

      <Field label="协议">
        <select value={transport} onChange={(e) => setTransport(e.target.value)} className={inputCls}>
          <option value="stdio">stdio</option>
          <option value="http">HTTP (SSE)</option>
        </select>
      </Field>

      {transport === "stdio" ? (
        <>
          <Field label="命令 (脚本路径)">
            <input value={command} onChange={(e) => setCommand(e.target.value)} className={inputCls} placeholder="npx / python / node ..." />
          </Field>

          <Field label="参数 (Args)">
            <div className="space-y-1">
              {args.map((a, i) => (
                <div key={i} className="flex items-center gap-1">
                  <span className="flex-1 truncate rounded bg-zinc-100 px-2 py-0.5 text-[10px] dark:bg-zinc-800">
                    {a}
                  </span>
                  <button onClick={() => removeArg(i)} className="text-[10px] text-zinc-400 hover:text-red-500">
                    ✕
                  </button>
                </div>
              ))}
              <div className="flex gap-1">
                <input
                  value={newArg}
                  onChange={(e) => setNewArg(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addArg()}
                  className={inputSmCls + " flex-1"}
                  placeholder="添加参数..."
                />
                <button onClick={addArg} className="rounded bg-zinc-200 px-2 text-[10px] dark:bg-zinc-700">
                  +
                </button>
              </div>
            </div>
          </Field>

          <Field label="环境变量 (Env)">
            <div className="space-y-1">
              {Object.entries(envRef).map(([k, v]) => (
                <div key={k} className="flex items-center gap-1">
                  <span className="truncate rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-mono dark:bg-zinc-800">
                    {k}
                  </span>
                  <span className="flex-1 truncate text-[10px] text-zinc-400">= {v ? "••••" : "(空)"}</span>
                  <button onClick={() => removeEnv(k)} className="text-[10px] text-zinc-400 hover:text-red-500">
                    ✕
                  </button>
                </div>
              ))}
              <div className="flex gap-1">
                <input
                  value={newEnvKey}
                  onChange={(e) => setNewEnvKey(e.target.value)}
                  className={inputSmCls + " w-24"}
                  placeholder="KEY"
                />
                <input
                  value={newEnvVal}
                  onChange={(e) => setNewEnvVal(e.target.value)}
                  className={inputSmCls + " flex-1"}
                  placeholder="VALUE"
                  type="password"
                />
                <button onClick={addEnv} className="rounded bg-zinc-200 px-2 text-[10px] dark:bg-zinc-700">
                  +
                </button>
              </div>
            </div>
          </Field>
        </>
      ) : (
        <Field label="URL">
          <input value={url} onChange={(e) => setUrl(e.target.value)} className={inputCls} placeholder="http://localhost:3000/sse" />
        </Field>
      )}

      <Field label="超时 (秒)">
        <input
          type="number"
          min={5}
          max={300}
          value={timeout}
          onChange={(e) => setTimeout_(Number(e.target.value))}
          className={inputCls}
        />
      </Field>

      <div className="flex gap-4">
        <Checkbox label="启用" checked={enabled} onChange={setEnabled} />
        <Checkbox label="自动启动" checked={autoStart} onChange={setAutoStart} />
      </div>

      <button
        onClick={handleSave}
        disabled={!name.trim() || create.isPending || update.isPending}
        className="w-full rounded bg-blue-500 py-2 text-xs font-medium text-white disabled:opacity-50"
      >
        {create.isPending || update.isPending ? "保存中..." : "保存"}
      </button>

      {isEdit && (
        <button
          onClick={handleDelete}
          disabled={del.isPending}
          className="w-full rounded border border-red-300 py-2 text-xs font-medium text-red-500 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
        >
          删除服务器
        </button>
      )}
    </div>
  );
}

// --- Shared helpers ---

const inputCls =
  "w-full rounded border border-zinc-300 px-2.5 py-1.5 text-xs dark:border-zinc-600 dark:bg-zinc-800";

const inputSmCls =
  "rounded border border-zinc-300 px-2 py-1 text-[10px] dark:border-zinc-600 dark:bg-zinc-800";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] text-zinc-500">{label}</label>
      {children}
    </div>
  );
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[11px]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3 w-3"
      />
      {label}
    </label>
  );
}

export default EditorDrawer;
