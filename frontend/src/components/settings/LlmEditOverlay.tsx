import { useState } from "react";
import { useCreateLlmProvider, useUpdateLlmProvider, LLM_TYPES, type LlmProvider } from "../../queries/useLlmQuery";

function LlmEditOverlay({ data, onClose }: { data: LlmProvider | null; onClose: () => void }) {
  const isEdit = !!data?.id;
  const create = useCreateLlmProvider();
  const update = useUpdateLlmProvider();

  const [name, setName] = useState(data?.name ?? "");
  const [type, setType] = useState(data?.type ?? "openai");
  const [apiKey, setApiKey] = useState(data?.api_key_ref ?? "");
  const [baseUrl, setBaseUrl] = useState(data?.base_url ?? "");
  const [model, setModel] = useState(data?.models?.[0]?.model_name ?? "");

  async function handleSave() {
    const payload = { name, type, api_key_ref: apiKey || undefined, base_url: baseUrl || undefined };
    if (isEdit) {
      await update.mutateAsync({ id: data!.id, ...payload });
    } else {
      await create.mutateAsync(payload);
    }
    onClose();
  }

  return (
    <div className="absolute inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-zinc-800/55" onClick={onClose} />

      {/* Panel - left aligned per Figma */}
      <div className="relative z-10 flex h-full w-[380px] flex-col overflow-auto bg-zinc-100 p-6 dark:bg-zinc-900">
        <h2 className="mb-6 text-base font-semibold text-zinc-700 dark:text-zinc-200">
          LLM配置
        </h2>

        <div className="flex-1 space-y-4">
          <Field label="名称">
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="例如: My OpenAI" />
          </Field>
          <Field label="类型">
            <select value={type} onChange={(e) => setType(e.target.value)} className={inputCls}>
              {LLM_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </Field>
          <Field label="API">
            <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} className={inputCls} placeholder="sk-..." type="password" />
          </Field>
          <Field label="URL">
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className={inputCls} placeholder="https://api.openai.com/v1" />
          </Field>
          <Field label="模型">
            <input value={model} onChange={(e) => setModel(e.target.value)} className={inputCls} placeholder="gpt-4o" />
          </Field>

          <button className="text-xs text-zinc-400 hover:text-zinc-600">更多配置项</button>
        </div>

        {/* Actions */}
        <div className="mt-6 flex items-center gap-2">
          <button
            onClick={onClose}
            className="rounded-2xl border border-zinc-200 bg-white px-5 py-2.5 text-sm text-zinc-600 shadow-sm dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim() || create.isPending || update.isPending}
            className="flex-1 rounded-2xl bg-blue-500 px-5 py-2.5 text-sm font-medium text-white shadow disabled:opacity-50"
          >
            {create.isPending || update.isPending ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputCls = "w-full rounded-xl border border-zinc-200 bg-white px-3 py-2.5 text-sm dark:border-zinc-600 dark:bg-zinc-800";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-zinc-500">{label}</label>
      {children}
    </div>
  );
}

export default LlmEditOverlay;
