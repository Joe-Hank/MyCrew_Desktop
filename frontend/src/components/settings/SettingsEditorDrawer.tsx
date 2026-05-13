import { useState } from "react";
import {
  useCreateLlmProvider,
  useUpdateLlmProvider,
  LLM_TYPES,
  type LlmProvider,
} from "../../queries/useLlmQuery";
import { useCreateMcpServer, useUpdateMcpServer } from "../../queries/useMcpQuery";
import SideDrawer, { DrawerFooter, FormField, inputCls, inputStyle } from "../common/SideDrawer";

export type SettingsEditorTarget =
  | { kind: "llm"; data: LlmProvider | null }
  | { kind: "mcp"; data: Record<string, unknown> | null };

function SettingsEditorDrawer({
  target,
  onClose,
}: {
  target: SettingsEditorTarget | null;
  onClose: () => void;
}) {
  const open = !!target;
  const titlePrefix = target?.data?.id ? "编辑" : "";

  return (
    <SideDrawer
      title={target ? `${titlePrefix}${target.kind === "llm" ? "LLM配置" : "MCP配置"}` : ""}
      open={open}
      onClose={onClose}
      onReset={() => undefined}
    >
      {target?.kind === "llm" && (
        <LlmForm key={target.data?.id ?? "new"} data={target.data} onDone={onClose} />
      )}
      {target?.kind === "mcp" && (
        <McpForm key={(target.data?.id as string) ?? "new"} data={target.data} onDone={onClose} />
      )}
    </SideDrawer>
  );
}

// ── LLM Form ────────────────────────────────────────────────────────

function LlmForm({ data, onDone }: { data: LlmProvider | null; onDone: () => void }) {
  const isEdit = !!data?.id;
  const create = useCreateLlmProvider();
  const update = useUpdateLlmProvider();

  const [name, setName] = useState(data?.name ?? "");
  const [type, setType] = useState(data?.type ?? "openai");
  const [apiKey, setApiKey] = useState(data?.api_key_ref ?? "");
  const [baseUrl, setBaseUrl] = useState(data?.base_url ?? "");
  const [model, setModel] = useState(data?.models?.[0]?.model_name ?? "");
  const [moreOpen, setMoreOpen] = useState(false);

  const saving = create.isPending || update.isPending;

  async function handleSave() {
    const payload = {
      name,
      type,
      api_key_ref: apiKey || undefined,
      base_url: baseUrl || undefined,
    };
    if (isEdit) {
      await update.mutateAsync({ id: data!.id, ...payload });
    } else {
      await create.mutateAsync(payload);
    }
    onDone();
  }

  return (
    <>
      <FormField label="名称">
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} style={inputStyle} placeholder="例如：My OpenAI" />
      </FormField>
      <FormField label="类型">
        <select value={type} onChange={(e) => setType(e.target.value)} className={inputCls} style={inputStyle}>
          {LLM_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </FormField>
      <FormField label="API">
        <input
          value={apiKey ?? ""}
          onChange={(e) => setApiKey(e.target.value)}
          className={inputCls} style={inputStyle}
          placeholder="sk-..."
          type="password"
        />
      </FormField>
      <FormField label="URL">
        <input
          value={baseUrl ?? ""}
          onChange={(e) => setBaseUrl(e.target.value)}
          className={inputCls} style={inputStyle}
          placeholder="https://api.openai.com/v1"
        />
      </FormField>
      <FormField label="模型">
        <input value={model} onChange={(e) => setModel(e.target.value)} className={inputCls} style={inputStyle} placeholder="gpt-4 / claude-opus..." />
      </FormField>

      <div className="mb-4 ml-12">
        <button
          onClick={() => setMoreOpen((v) => !v)}
          className="text-xs"
          style={{ color: "var(--color-ink-faint)" }}
        >
          {moreOpen ? "▲ 收起" : "▽ 更多配置项"}
        </button>
        {moreOpen && (
          <div className="mt-2 rounded-lg bg-white p-3 text-xs" style={{ color: "var(--color-ink-faint)" }}>
            额外的模型管理（多模型 / 思考模式 / 最大 token）将在后续版本支持。
          </div>
        )}
      </div>

      <div className="mt-6">
        <DrawerFooter
          onCancel={onDone}
          onSave={handleSave}
          saving={saving}
          saveDisabled={!name.trim() || !type}
        />
      </div>
    </>
  );
}

// ── MCP Form ────────────────────────────────────────────────────────

function McpForm({ data, onDone }: { data: Record<string, unknown> | null; onDone: () => void }) {
  const isEdit = !!data?.id;
  const create = useCreateMcpServer();
  const update = useUpdateMcpServer();

  const [name, setName] = useState((data?.name as string) ?? "");
  const [transport, setTransport] = useState((data?.transport as string) ?? "stdio");
  const [command, setCommand] = useState((data?.command as string) ?? "");
  const [args, setArgs] = useState(
    Array.isArray(data?.args) ? (data?.args as string[]).join(" ") : ""
  );
  const [url, setUrl] = useState((data?.url as string) ?? "");
  const [moreOpen, setMoreOpen] = useState(false);

  const saving = create.isPending || update.isPending;

  async function handleSave() {
    const payload: Record<string, unknown> = {
      name,
      transport,
      args: args ? args.split(/\s+/).filter(Boolean) : [],
    };
    if (transport === "stdio") {
      payload.command = command;
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

  return (
    <>
      <FormField label="名称">
        <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} style={inputStyle} placeholder="例如：Unity-MCP" />
      </FormField>
      <FormField label="协议">
        <select value={transport} onChange={(e) => setTransport(e.target.value)} className={inputCls} style={inputStyle}>
          <option value="stdio">stdio</option>
          <option value="http">HTTP/SSE</option>
        </select>
      </FormField>
      <FormField label="参数">
        <input value={args} onChange={(e) => setArgs(e.target.value)} className={inputCls} style={inputStyle} placeholder="--port 8090" />
      </FormField>
      {transport === "stdio" ? (
        <FormField label="路径">
          <div className="flex items-center gap-2">
            <input
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              className={inputCls} style={inputStyle}
              placeholder="E:\CrewAI\..."
            />
            <button
              className="rounded-lg bg-white p-2"
              style={{ color: "var(--color-ink-muted)" }}
              title="选择文件"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
            </button>
          </div>
        </FormField>
      ) : (
        <FormField label="URL">
          <input value={url} onChange={(e) => setUrl(e.target.value)} className={inputCls} style={inputStyle} placeholder="http://localhost:8090" />
        </FormField>
      )}

      <div className="mb-4 ml-12">
        <button
          onClick={() => setMoreOpen((v) => !v)}
          className="text-xs"
          style={{ color: "var(--color-ink-faint)" }}
        >
          {moreOpen ? "▲ 收起" : "▽ 更多配置项"}
        </button>
        {moreOpen && (
          <div className="mt-2 rounded-lg bg-white p-3 text-xs" style={{ color: "var(--color-ink-faint)" }}>
            环境变量、超时、自动重连等配置将在后续支持。
          </div>
        )}
      </div>

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

export default SettingsEditorDrawer;
