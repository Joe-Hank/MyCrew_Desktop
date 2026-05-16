import { useState } from "react";
import {
  useCreateLlmProvider,
  useUpdateLlmProvider,
  LLM_TYPES,
  type LlmProvider,
} from "../../queries/useLlmQuery";
import {
  useCreateMcpServer,
  useUpdateMcpServer,
  useMcpTemplates,
  type McpTemplate,
  type McpTemplateField,
} from "../../queries/useMcpQuery";
import { ApiError } from "../../net/api";
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
//
// Strategy C: a template picker + a form that renders the chosen
// template's declared fields (label / type / placeholder / required).
// On save the frontend posts { template_id, template_values } and the
// backend assembles the concrete command/args/url/env_ref. Submitting
// with a missing required field or a ${placeholder} value gets a
// per-field validation error response which we surface inline.
//
// "custom" template falls back to a free-form command/args/url editor
// for exotic MCP servers not covered by the catalogue.

function McpForm({ data, onDone }: { data: Record<string, unknown> | null; onDone: () => void }) {
  const isEdit = !!data?.id;
  const create = useCreateMcpServer();
  const update = useUpdateMcpServer();
  const { data: templates = [], isLoading: templatesLoading } = useMcpTemplates();

  // Default to the existing row's template (set by backfill on start),
  // or "custom" as a safe fallback when the row predates the migration.
  const initialTemplateId = (data?.template_id as string) || "custom";
  const initialValues = (data?.template_values as Record<string, unknown>) || {};

  const [name, setName] = useState((data?.name as string) ?? "");
  const [templateId, setTemplateId] = useState<string>(initialTemplateId);
  const [values, setValues] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(initialValues)) {
      out[k] = v == null ? "" : String(v);
    }
    return out;
  });

  // For 'custom' template — direct command/args/url editing
  const [customTransport, setCustomTransport] = useState(
    (data?.transport as string) ?? "stdio",
  );
  const [customCommand, setCustomCommand] = useState((data?.command as string) ?? "");
  const [customArgs, setCustomArgs] = useState(
    Array.isArray(data?.args) ? (data?.args as string[]).join(" ") : "",
  );
  const [customUrl, setCustomUrl] = useState((data?.url as string) ?? "");

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [topError, setTopError] = useState<string>("");

  const selectedTemplate: McpTemplate | undefined = templates.find(
    (t) => t.id === templateId,
  );

  const saving = create.isPending || update.isPending;

  function setValue(key: string, v: string) {
    setValues((prev) => ({ ...prev, [key]: v }));
    setFieldErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  async function handleSave() {
    setFieldErrors({});
    setTopError("");

    const payload: Record<string, unknown> = { name, template_id: templateId };
    if (templateId === "custom") {
      payload.transport = customTransport;
      payload.args = customArgs ? customArgs.split(/\s+/).filter(Boolean) : [];
      if (customTransport === "stdio") {
        payload.command = customCommand;
      } else {
        payload.url = customUrl;
      }
    } else {
      // Pass values through as-is; the backend's assemble() does
      // substitution + validation. Coerce number fields up-front
      // so the user can type "8090" and it goes over the wire as int.
      const tpl = selectedTemplate;
      const sanitized: Record<string, unknown> = {};
      for (const f of tpl?.fields ?? []) {
        const raw = values[f.key] ?? "";
        if (f.type === "number" && raw !== "") {
          const n = Number(raw);
          sanitized[f.key] = Number.isFinite(n) ? n : raw;
        } else {
          sanitized[f.key] = raw;
        }
      }
      payload.template_values = sanitized;
    }

    try {
      if (isEdit) {
        await update.mutateAsync({ id: data!.id as string, ...payload });
      } else {
        await create.mutateAsync(payload);
      }
      onDone();
    } catch (err) {
      // The backend envelope returns { code: 'template_validation',
      // field_errors: [{field, message}] } on schema failures.
      if (err instanceof ApiError && err.kind === "envelope") {
        const env = (err as ApiError & {
          code?: string;
          cause?: { error?: { field_errors?: { field: string; message: string }[] } };
        });
        // ApiError stashes cause but the field_errors live on the raw
        // envelope. Easier: just parse the message string fallback.
        // For now, surface the envelope message at the top.
        setTopError(env.message || "保存失败");
      } else {
        setTopError(err instanceof Error ? err.message : String(err));
      }
    }
  }

  return (
    <>
      <FormField label="名称">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={inputCls}
          style={inputStyle}
          placeholder="例如：Unity / 我的 Figma"
        />
      </FormField>

      <FormField label="类型">
        <select
          value={templateId}
          onChange={(e) => {
            setTemplateId(e.target.value);
            setFieldErrors({});
            setTopError("");
          }}
          className={inputCls}
          style={inputStyle}
          disabled={templatesLoading}
        >
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        {selectedTemplate && (
          <p
            className="mt-1 text-[11px]"
            style={{ color: "var(--color-ink-faint)" }}
          >
            {selectedTemplate.description}
          </p>
        )}
      </FormField>

      {/* Template-specific fields */}
      {selectedTemplate &&
        selectedTemplate.id !== "custom" &&
        selectedTemplate.fields.map((f) => (
          <FormField key={f.key} label={f.label}>
            <TemplateFieldInput
              field={f}
              value={values[f.key] ?? String(f.default ?? "")}
              onChange={(v) => setValue(f.key, v)}
              error={fieldErrors[f.key]}
            />
            {f.description && !fieldErrors[f.key] && (
              <p
                className="mt-1 text-[11px]"
                style={{ color: "var(--color-ink-faint)" }}
              >
                {f.description}
              </p>
            )}
            {fieldErrors[f.key] && (
              <p className="mt-1 text-[11px]" style={{ color: "#dc2626" }}>
                {fieldErrors[f.key]}
              </p>
            )}
          </FormField>
        ))}

      {/* Custom template — free-form editor */}
      {templateId === "custom" && (
        <>
          <FormField label="协议">
            <select
              value={customTransport}
              onChange={(e) => setCustomTransport(e.target.value)}
              className={inputCls}
              style={inputStyle}
            >
              <option value="stdio">stdio</option>
              <option value="http">HTTP/SSE</option>
            </select>
          </FormField>
          {customTransport === "stdio" ? (
            <>
              <FormField label="命令">
                <input
                  value={customCommand}
                  onChange={(e) => setCustomCommand(e.target.value)}
                  className={inputCls}
                  style={inputStyle}
                  placeholder="npx / uvx / python / 绝对路径"
                />
              </FormField>
              <FormField label="参数">
                <input
                  value={customArgs}
                  onChange={(e) => setCustomArgs(e.target.value)}
                  className={inputCls}
                  style={inputStyle}
                  placeholder="-y my-mcp-server --foo bar"
                />
              </FormField>
            </>
          ) : (
            <FormField label="URL">
              <input
                value={customUrl}
                onChange={(e) => setCustomUrl(e.target.value)}
                className={inputCls}
                style={inputStyle}
                placeholder="http://localhost:8090/mcp"
              />
            </FormField>
          )}
        </>
      )}

      {topError && (
        <div
          className="mb-3 rounded-md px-3 py-2 text-xs"
          style={{
            backgroundColor: "rgba(220, 38, 38, 0.08)",
            color: "#dc2626",
            border: "1px solid rgba(220, 38, 38, 0.2)",
          }}
        >
          {topError}
        </div>
      )}

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

function TemplateFieldInput({
  field,
  value,
  onChange,
  error,
}: {
  field: McpTemplateField;
  value: string;
  onChange: (v: string) => void;
  error?: string;
}) {
  const htmlType =
    field.type === "password"
      ? "password"
      : field.type === "number"
        ? "number"
        : "text";
  return (
    <input
      type={htmlType}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={inputCls}
      style={{
        ...inputStyle,
        borderColor: error
          ? "rgba(220, 38, 38, 0.5)"
          : (inputStyle as { borderColor?: string }).borderColor,
      }}
      placeholder={field.placeholder ?? ""}
      autoComplete={field.type === "password" ? "new-password" : undefined}
    />
  );
}

export default SettingsEditorDrawer;
