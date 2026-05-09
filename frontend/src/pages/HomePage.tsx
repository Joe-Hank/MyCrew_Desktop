import McpStatusBar from "../components/home/McpStatusBar";
import ProjectGrid from "../components/home/ProjectGrid";
import InceptionDrawer from "../components/inception/InceptionDrawer";
import { useInceptionStore } from "../stores/useInceptionStore";

function HomePage() {
  const { openDrawer } = useInceptionStore();

  function handleStart(projectId: string) {
    // Phase 5b+ will wire workflow start/pause toggle
    console.log("start/pause project:", projectId);
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar - top */}
      <div className="flex items-center px-6 pt-4">
        <button
          onClick={() => openDrawer()}
          className="rounded-2xl bg-blue-500 px-5 py-2.5 text-sm font-medium text-white shadow transition-colors hover:bg-blue-600"
        >
          新建项目  +
        </button>
      </div>

      {/* Project grid - center */}
      <div className="flex-1 overflow-auto px-6 pt-4">
        <ProjectGrid onStart={handleStart} />
      </div>

      {/* Bottom status bars */}
      <div className="space-y-0 border-t border-zinc-200 dark:border-zinc-800">
        {/* Tokens bar */}
        <div className="flex items-center gap-2 px-4 py-2">
          <span className="text-xs text-zinc-600 dark:text-zinc-400">Tokens：</span>
          <TokenPill name="ClaudeCode" pct={0} />
          <TokenPill name="GPT" pct={0} />
          <TokenPill name="Qwen" pct={34} />
          <TokenPill name="MIMO" pct={34} />
          <TokenPill name="Deepseek" pct={34} />
          <TokenPill name="GLM" pct={0} />
        </div>
        {/* MCP connection bar */}
        <div className="flex items-center gap-2 border-t border-zinc-100 px-4 py-2 dark:border-zinc-800">
          <span className="text-xs text-zinc-600 dark:text-zinc-400">MPC连接：</span>
          <McpStatusBar />
          <div className="ml-auto flex gap-2">
            <button className="rounded-2xl border border-zinc-200 bg-white px-4 py-1.5 text-xs text-zinc-600 shadow-sm dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              连接
            </button>
            <button className="rounded-2xl border border-zinc-200 bg-white px-4 py-1.5 text-xs text-zinc-600 shadow-sm dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              刷新
            </button>
          </div>
        </div>
      </div>

      {/* Inception drawer (overlay) */}
      <InceptionDrawer />
    </div>
  );
}

function TokenPill({ name, pct }: { name: string; pct: number }) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1 dark:border-zinc-700 dark:bg-zinc-800">
      <span className="text-xs text-zinc-600 dark:text-zinc-300">{name}</span>
      <span className="text-xs text-zinc-400">{pct}%</span>
    </div>
  );
}

export default HomePage;
