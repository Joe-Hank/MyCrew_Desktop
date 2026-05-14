import { usePermissions, useUpdatePermissions } from "../../queries/useConfigQuery";
import {
  useComplianceMode,
  useSetComplianceMode,
  type ComplianceMode,
} from "../../queries/useSettingsQuery";
import QueryErrorState from "../common/QueryErrorState";

const PERMISSION_INFO: Record<string, { label: string; desc: string }> = {
  file_read: { label: "文件读取", desc: "允许 Agent 读取文件内容" },
  file_write: { label: "文件写入", desc: "允许 Agent 创建新文件" },
  file_delete: { label: "文件删除", desc: "允许 Agent 删除文件" },
  file_modify: { label: "文件修改", desc: "允许 Agent 修改已有文件" },
  folder_read: { label: "文件夹读取", desc: "允许 Agent 列出目录内容" },
  dir_create: { label: "目录创建", desc: "允许 Agent 创建新目录" },
  cmd_exec: { label: "命令执行", desc: "允许 Agent 执行系统命令" },
  bg_cmd: { label: "后台命令", desc: "允许 Agent 启动后台进程" },
  git: { label: "Git 操作", desc: "允许 Agent 执行 Git 命令" },
};

function PermissionTable() {
  const { data: permissions = [], isLoading, isError, error, refetch, isFetching } = usePermissions();
  const updateMutation = useUpdatePermissions();

  if (isLoading) {
    return <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>加载中...</div>;
  }

  if (isError) {
    return (
      <QueryErrorState
        title="读取权限配置失败"
        error={error}
        onRetry={() => refetch()}
        isFetching={isFetching}
      />
    );
  }

  function handleToggle(id: string, currentAllowed: boolean) {
    updateMutation.mutate([{ id, allowed: !currentAllowed }]);
  }

  return (
    <div className="space-y-3">
      {/* Compliance mode toggle — gates whether Plan Maker refuses
          potentially-violating content. Default 自由（free）。 */}
      <ComplianceModeRow />

      <div
        className="space-y-1.5 rounded-lg px-4 py-2.5 text-xs leading-relaxed"
        style={{
          backgroundColor: "rgba(245, 158, 11, 0.12)",
          color: "#92400e",
        }}
      >
        <div>
          ⚠️ 这些权限控制 Agent 在执行任务时可以进行的系统操作。**关闭某项权限后，
          所有 MCP / 内置工具中需要该权限的调用会被立即拦截**（任务日志里会看到
          <code className="font-mono">[PermissionDenied]</code> 字样）。
        </div>
        <div style={{ color: "#7c4400" }}>
          高危操作（如 Blender 任意代码执行）即使在权限开启时，也会在每次调用前
          弹窗询问；可在底部 <code className="font-mono">{'>_ 日志'}</code> 抽屉中
          查看每次工具调用的完整审计记录（<code className="font-mono">tool.invoked</code>）。
        </div>
      </div>

      <div className="overflow-hidden rounded-xl bg-white" style={{ border: "1px solid var(--color-border-soft)" }}>
        {(permissions as Record<string, unknown>[]).map((p, i) => {
          const info = PERMISSION_INFO[p.kind as string];
          return (
            <div
              key={p.id as string}
              className="flex items-center justify-between px-5 py-3"
              style={i === 0 ? {} : { borderTop: "1px solid var(--color-border-soft)" }}
            >
              <div>
                <div className="text-sm font-medium" style={{ color: "var(--color-ink-soft)" }}>
                  {info?.label ?? (p.kind as string)}
                </div>
                <div className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                  {info?.desc ?? (p.kind as string)}
                </div>
              </div>
              <button
                onClick={() => handleToggle(p.id as string, p.allowed as boolean)}
                disabled={updateMutation.isPending}
                className="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-60"
                style={{
                  // Slimmer track (20×36 vs old 24×44) + soft inner border on
                  // OFF so the chip reads as "off" rather than "loading".
                  // Active green gets a subtle glow for polish.
                  backgroundColor: p.allowed ? "#10b981" : "var(--color-surface-alt)",
                  border: p.allowed ? "none" : "1px solid var(--color-border-soft)",
                  boxShadow: p.allowed
                    ? "0 0 0 1px rgba(16, 185, 129, 0.15)"
                    : "none",
                }}
              >
                <span
                  className="absolute h-4 w-4 rounded-full bg-white shadow-sm transition-transform"
                  style={{ transform: p.allowed ? "translateX(18px)" : "translateX(2px)" }}
                />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Compliance mode row — pill segmented control matching ProcessToggle
 *  pattern (sliding white indicator + dimmed inactive label). 自由 is the
 *  default; 和谐 makes Plan Maker refuse violating content. */
function ComplianceModeRow() {
  const { data: mode = "free" } = useComplianceMode();
  const setMut = useSetComplianceMode();
  const isHarmonious = mode === "harmonious";
  const SEG_W = 56;

  function pick(target: ComplianceMode) {
    if (target !== mode) setMut.mutate(target);
  }

  return (
    <div
      className="flex items-center justify-between rounded-lg px-4 py-3"
      style={{
        backgroundColor: "var(--color-card)",
        border: "1px solid var(--color-border-soft)",
      }}
    >
      <div className="flex-1">
        <div
          className="text-sm font-medium"
          style={{ color: "var(--color-ink-soft)" }}
        >
          合规模式
        </div>
        <div className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
          自由：允许任意创作；和谐：拦截涉嫌违法/政治/色情/暴力的请求
        </div>
      </div>
      <span
        role="radiogroup"
        className="relative inline-flex items-center rounded-full p-0.5"
        style={{
          width: SEG_W * 2 + 4,
          height: 26,
          backgroundColor: "var(--color-surface-alt)",
          opacity: setMut.isPending ? 0.6 : 1,
        }}
      >
        <span
          className="absolute top-0.5 left-0.5 rounded-full bg-white shadow-sm transition-transform duration-200"
          style={{
            width: SEG_W,
            height: 22,
            transform: isHarmonious ? `translateX(${SEG_W}px)` : "translateX(0)",
          }}
        />
        <button
          onClick={() => pick("free")}
          disabled={setMut.isPending}
          className="relative z-10 flex items-center justify-center text-xs font-medium transition-colors"
          style={{
            width: SEG_W,
            color: isHarmonious ? "var(--color-ink-disabled)" : "var(--color-ink)",
          }}
        >
          自由
        </button>
        <button
          onClick={() => pick("harmonious")}
          disabled={setMut.isPending}
          className="relative z-10 flex items-center justify-center text-xs font-medium transition-colors"
          style={{
            width: SEG_W,
            color: isHarmonious ? "var(--color-ink)" : "var(--color-ink-disabled)",
          }}
        >
          和谐
        </button>
      </span>
    </div>
  );
}

export default PermissionTable;
