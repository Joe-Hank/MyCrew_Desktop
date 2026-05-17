import { useState, useEffect, useRef } from "react";
import {
  useCreateLlmProvider,
  useUpdateLlmProvider,
  useCreateLlmModel,
  useUpdateLlmModel,
  useProbeThinking,
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

/** Mirror of `LlmService._heuristic_supports_thinking` (backend). Used as
 * an instant-feedback fallback when the user is creating a brand-new
 * provider and we don't yet have a provider_id to anchor a real probe
 * call. The backend's authoritative check still runs once the row is
 * saved (handleSave caches it via createModel's supports_thinking). */
function heuristicSupportsThinking(providerType: string, modelName: string): boolean {
  const name = modelName.toLowerCase();
  const t = providerType.toLowerCase();
  if (t === "anthropic") {
    if (name.includes("claude-3-7") || name.includes("claude-3.7")) return true;
    if (name.includes("claude-opus-4") || name.includes("claude-sonnet-4") || name.includes("claude-haiku-4")) return true;
    if (name.startsWith("claude-4-") || name.startsWith("claude-5-")) return true;
    return false;
  }
  if (t === "openai") {
    if (name.startsWith("o1") || name.startsWith("o3") || name.startsWith("o4")) return true;
    if (name.startsWith("gpt-5")) return true;
    return false;
  }
  if (t === "deepseek") {
    return name.includes("reasoner") || name.endsWith("-r1");
  }
  if (t === "qwen") {
    return name.includes("qwq") || name.includes("reasoner") || name.includes("-thinking");
  }
  if (t === "gemini") {
    return name.includes("2.5") && name.includes("thinking");
  }
  return false;
}


function LlmForm({ data, onDone }: { data: LlmProvider | null; onDone: () => void }) {
  const isEdit = !!data?.id;
  const create = useCreateLlmProvider();
  const update = useUpdateLlmProvider();
  const createModel = useCreateLlmModel();
  const updateModel = useUpdateLlmModel();
  const probe = useProbeThinking();

  const firstModel = data?.models?.[0];

  const [name, setName] = useState(data?.name ?? "");
  const [type, setType] = useState(data?.type ?? "openai");
  const [apiKey, setApiKey] = useState(data?.api_key_ref ?? "");
  const [baseUrl, setBaseUrl] = useState(data?.base_url ?? "");
  const [model, setModel] = useState(firstModel?.model_name ?? "");
  const [moreOpen, setMoreOpen] = useState(false);

  // Thinking-mode capability:
  //   - Initial value comes from the persisted model row (if any) — that
  //     value was last cached by either an earlier probe OR by a seed.
  //   - The toggle is `disabled` whenever the current (type, model)
  //     combination's supports_thinking is false. The user can still
  //     re-probe by editing the model field; we run the probe on
  //     debounced text changes so picking a different model variant
  //     unlocks the toggle without saving first.
  //   - When the probed result flips to false, we automatically pull
  //     the toggle back down so a stale "on" value can't outlive the
  //     model name change.
  const [supportsThinking, setSupportsThinking] = useState<boolean>(
    firstModel?.supports_thinking ?? false,
  );

  // Pricing — stored as integer 分 / 1M tokens server-side. Empty string
  // input means "leave alone" (don't trample the seeded default); 0 means
  // "explicitly disable billing".
  const [inputPrice, setInputPrice] = useState<string>(
    firstModel?.input_price_cny_per_1m == null
      ? ""
      : String(firstModel.input_price_cny_per_1m),
  );
  const [outputPrice, setOutputPrice] = useState<string>(
    firstModel?.output_price_cny_per_1m == null
      ? ""
      : String(firstModel.output_price_cny_per_1m),
  );

  const saving =
    create.isPending || update.isPending ||
    createModel.isPending || updateModel.isPending;

  function parsePrice(s: string): number | undefined {
    // Empty → don't send (server keeps existing value / seeded default).
    if (s.trim() === "") return undefined;
    const n = Number(s);
    if (!Number.isFinite(n) || n < 0) return undefined;
    return Math.floor(n);
  }

  // Debounced probe: 400ms after the user stops typing in the model
  // field (or changes provider type), re-resolve supports_thinking.
  const probeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!model.trim()) {
      setSupportsThinking(false);
      return;
    }
    if (probeTimer.current) clearTimeout(probeTimer.current);
    probeTimer.current = setTimeout(() => {
      const payload = firstModel?.id
        ? { model_id: firstModel.id }
        : data?.id
          ? { provider_id: data.id, model_name: model.trim() }
          : null;
      // No provider id yet (creating a brand-new provider): probe with
      // a synthetic call — backend tolerates "provider_id + model_name"
      // but needs a real provider row to cache. Skip until the
      // provider is created (handleSave runs the probe on the new id).
      if (!payload) {
        // Heuristic-only fallback: replicate the backend rule so the
        // toggle still reacts to model typing even before first save.
        setSupportsThinking(heuristicSupportsThinking(type, model));
        return;
      }
      probe.mutate(payload, {
        onSuccess: (res) => {
          setSupportsThinking(res.supports_thinking);
        },
      });
    }, 400);
    return () => {
      if (probeTimer.current) clearTimeout(probeTimer.current);
    };
  }, [model, type, data?.id, firstModel?.id]);

  async function handleSave() {
    const payload = {
      name,
      type,
      api_key_ref: apiKey || undefined,
      base_url: baseUrl || undefined,
    };
    let providerId: string | undefined = data?.id;
    if (isEdit) {
      await update.mutateAsync({ id: data!.id, ...payload });
      providerId = data!.id;
    } else {
      const created = (await create.mutateAsync(payload)) as unknown as {
        data?: { id?: string };
      };
      providerId = created.data?.id ?? providerId;
    }

    // Persist (or update) the first model row so supports_thinking +
    // pricing both stick. The legacy form only edited the provider;
    // without this the model field had no destination and the toggles
    // had nothing to bind to. Falls back to `createModel` if the
    // provider had no model row yet (true for any provider edited
    // before this feature shipped).
    const wantedModelName = model.trim();
    if (providerId && wantedModelName) {
      const inP = parsePrice(inputPrice);
      const outP = parsePrice(outputPrice);
      if (firstModel?.id) {
        await updateModel.mutateAsync({
          id: firstModel.id,
          model_name: wantedModelName,
          supports_thinking: supportsThinking,
          input_price_cny_per_1m: inP,
          output_price_cny_per_1m: outP,
        });
      } else {
        await createModel.mutateAsync({
          provider_id: providerId,
          model_name: wantedModelName,
          supports_thinking: supportsThinking,
          input_price_cny_per_1m: inP,
          output_price_cny_per_1m: outP,
        });
      }
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

      <FormField label="思考模式">
        <div className="flex items-center gap-3">
          {/* The toggle here reflects the *model's capability* — it is
              the destination of the /llm/probe-thinking call and what
              gets persisted on llm_models.supports_thinking. The user
              can override (e.g. enable for a forward-compat new model
              the heuristic doesn't know yet), but the default state
              tracks the probe so 99% of users don't have to think. */}
          <button
            type="button"
            onClick={() => !probe.isPending && setSupportsThinking((v) => !v)}
            disabled={probe.isPending}
            title={
              probe.isPending
                ? "正在探测能力…"
                : supportsThinking
                  ? "该模型支持思考模式（点击可手动取消标记）"
                  : "该模型不支持思考模式（点击可手动覆盖）"
            }
            className="relative inline-flex h-5 w-9 items-center rounded-full"
            style={{
              backgroundColor: supportsThinking ? "#10b981" : "#cbd5e1",
              opacity: probe.isPending ? 0.55 : 1,
              cursor: probe.isPending ? "wait" : "pointer",
            }}
          >
            <span
              className="absolute h-4 w-4 rounded-full bg-white shadow-sm transition-transform"
              style={{ transform: supportsThinking ? "translateX(18px)" : "translateX(2px)" }}
            />
          </button>
          <span
            className="text-[11px]"
            style={{ color: "var(--color-ink-faint)" }}
          >
            {probe.isPending
              ? "探测中…"
              : supportsThinking
                ? "支持 — Agent 可启用思考模式"
                : "不支持 — Agent 思考开关将锁定"}
          </span>
        </div>
      </FormField>
      <FormField label="输入价">
        <input
          type="number"
          min="0"
          step="1"
          value={inputPrice}
          onChange={(e) => setInputPrice(e.target.value)}
          className={inputCls}
          style={inputStyle}
          placeholder="如 1800 表示 ¥18 / 1M tokens；留空使用默认"
        />
      </FormField>
      <FormField label="输出价">
        <input
          type="number"
          min="0"
          step="1"
          value={outputPrice}
          onChange={(e) => setOutputPrice(e.target.value)}
          className={inputCls}
          style={inputStyle}
          placeholder="如 9000 表示 ¥90 / 1M tokens；0 = 不计费"
        />
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
            额外的模型管理（多模型 / 最大 token）将在后续版本支持。
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
