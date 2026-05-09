import { useState } from "react";

function McpEditOverlay({ data, onClose }: { data: Record<string, unknown> | null; onClose: () => void }) {
  const [name, setName] = useState((data?.name as string) ?? "");
  const [transport, setTransport] = useState((data?.transport as string) ?? "stdio");
  const [args, setArgs] = useState((data?.args as string) ?? "");
  const [scriptPath, setScriptPath] = useState((data?.command as string) ?? "");

  function handleSave() {
    // TODO: wire to mutation
    onClose();
  }

  return (
    <div className="absolute inset-0 z-50 flex">
      <div className="absolute inset-0 bg-zinc-800/55" onClick={onClose} />

      <div className="relative z-10 flex h-full w-[380px] flex-col overflow-auto bg-zinc-100 p-6 dark:bg-zinc-900">
        <h2 className="mb-6 text-base font-semibold text-zinc-700 dark:text-zinc-200">
          MCP配置
        </h2>

        <div className="flex-1 space-y-4">
          <Field label="名称">
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="例如: Unity-MCP" />
          </Field>
          <Field label="协议">
            <select value={transport} onChange={(e) => setTransport(e.target.value)} className={inputCls}>
              <option value="stdio">stdio</option>
              <option value="http">HTTP/SSE</option>
            </select>
          </Field>
          <Field label="参数">
            <input value={args} onChange={(e) => setArgs(e.target.value)} className={inputCls} placeholder="--port 8090" />
          </Field>
          <Field label="路径">
            <div className="flex gap-2">
              <input value={scriptPath} onChange={(e) => setScriptPath(e.target.value)} className={inputCls + " flex-1"} placeholder="E:\CrewAI\..." />
              <button className="shrink-0 rounded-xl border border-zinc-200 bg-white p-2.5 text-zinc-500 shadow-sm dark:border-zinc-600 dark:bg-zinc-800">
                📁
              </button>
            </div>
          </Field>

          <button className="text-xs text-zinc-400 hover:text-zinc-600">更多配置项</button>
        </div>

        <div className="mt-6 flex items-center gap-2">
          <button
            onClick={onClose}
            className="rounded-2xl border border-zinc-200 bg-white px-5 py-2.5 text-sm text-zinc-600 shadow-sm dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim()}
            className="flex-1 rounded-2xl bg-blue-500 px-5 py-2.5 text-sm font-medium text-white shadow disabled:opacity-50"
          >
            保存
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

export default McpEditOverlay;
