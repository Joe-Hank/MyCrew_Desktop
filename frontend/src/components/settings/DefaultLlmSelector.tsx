import { useConfig, useUpdateConfig } from "../../queries/useConfigQuery";
import type { LlmProvider } from "../../queries/useLlmQuery";

/**
 * Two-row default LLM selector shown at the top of the LLM tab.
 * - default_inception_model: used when creating new inception sessions
 * - default_agent_model: used when creating new agents
 *
 * Each stores a value like "provider_id:model_id" in app_settings.
 */
function DefaultLlmSelector({ providers }: { providers: LlmProvider[] }) {
  const { data: config = {} } = useConfig();
  const updateConfig = useUpdateConfig();

  const inceptionDefault = (config as Record<string, string>).default_inception_model ?? "";
  const agentDefault = (config as Record<string, string>).default_agent_model ?? "";

  // Build flat list of all provider:model combos
  const options: { value: string; label: string }[] = [];
  for (const p of providers) {
    if (p.models && p.models.length > 0) {
      for (const m of p.models) {
        options.push({
          value: `${p.id}:${m.id}`,
          label: `${p.name} / ${m.label || m.model_name}`,
        });
      }
    } else {
      // Provider with no models yet
      options.push({
        value: `${p.id}:`,
        label: `${p.name} (无模型)`,
      });
    }
  }

  function handleChange(key: string, value: string) {
    updateConfig.mutate({ key, value });
  }

  return (
    <div className="flex items-center gap-6 border-b border-zinc-200 bg-zinc-50 px-4 py-2 dark:border-zinc-800 dark:bg-zinc-900/50">
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-zinc-500">立项默认:</span>
        <select
          value={inceptionDefault}
          onChange={(e) => handleChange("default_inception_model", e.target.value)}
          className="rounded border border-zinc-300 px-2 py-1 text-[11px] dark:border-zinc-600 dark:bg-zinc-800"
        >
          <option value="">未设置</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-[11px] text-zinc-500">Agent 默认:</span>
        <select
          value={agentDefault}
          onChange={(e) => handleChange("default_agent_model", e.target.value)}
          className="rounded border border-zinc-300 px-2 py-1 text-[11px] dark:border-zinc-600 dark:bg-zinc-800"
        >
          <option value="">未设置</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

export default DefaultLlmSelector;
