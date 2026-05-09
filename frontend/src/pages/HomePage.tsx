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
      {/* MCP status bar */}
      <div className="border-b border-zinc-200 dark:border-zinc-800">
        <McpStatusBar />
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2 dark:border-zinc-800">
        <h1 className="text-sm font-semibold">项目</h1>
        <button
          onClick={() => {
            openDrawer();
          }}
          className="rounded bg-blue-500 px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-600"
        >
          + 新建项目
        </button>
      </div>

      {/* Project grid */}
      <div className="flex-1 overflow-auto">
        <ProjectGrid onStart={handleStart} />
      </div>

      {/* Inception drawer (overlay) */}
      <InceptionDrawer />
    </div>
  );
}

export default HomePage;
