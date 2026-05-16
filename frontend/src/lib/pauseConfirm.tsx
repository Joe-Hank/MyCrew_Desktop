/**
 * Cooperative-pause confirm dialog (PM v4 Q7).
 *
 * Pause is checked at task / Crew-step boundaries, not mid-LLM-call.
 * This dialog tells the user up front so a "stuck for 30 seconds after
 * I clicked pause" reaction reads as expected behaviour, not a bug.
 *
 * Shared between TaskHeader's project-level pause button and
 * TaskPage's per-task pause action (which routes through the same
 * project-level pause because the backend has no per-task pause —
 * the smallest cancellation unit is the project).
 */
import type { ReactNode } from "react";
import type { useDismissibleConfirm } from "../components/common/ConfirmDialog";

export async function askPauseConfirm(
  confirm: ReturnType<typeof useDismissibleConfirm>,
  runningCount: number,
): Promise<boolean> {
  const body: ReactNode = (
    <>
      <p>
        {runningCount > 0
          ? `当前有 ${runningCount} 个任务正在跑。`
          : "当前可能有任务步骤正在跑。"}
        点击暂停后，<strong>正在执行的 LLM 调用不会被打断</strong>，
        要等本步骤跑完才真正停下来。下一个任务/步骤就不会再启动了。
      </p>
      <p className="mt-2 text-xs" style={{ color: "var(--color-ink-faint)" }}>
        这是 PM v4 软暂停的设计——避免把 LLM 半途砍掉留下半成品。
        如果想立刻终止整个项目，使用「终止」而不是「暂停」。
      </p>
    </>
  );

  const result = await confirm({
    dialogId: "pause.waits_for_current_step",
    title: "暂停将在当前步骤结束后生效",
    body,
    options: [
      { value: "ok", label: "明白了，暂停", primary: true },
      { value: "cancel", label: "再想想", tone: "subtle" },
    ],
    allowDismiss: true,
  });
  return result.choice === "ok";
}
