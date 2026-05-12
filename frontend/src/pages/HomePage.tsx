import { useState } from "react";
import ProjectGrid from "../components/home/ProjectGrid";
import StatusBars from "../components/home/StatusBars";
import InceptionDrawer from "../components/inception/InceptionDrawer";
import { useInceptionStore } from "../stores/useInceptionStore";
import { useProjects } from "../queries/useProjectQuery";

function HomePage() {
  const { openDrawer } = useInceptionStore();
  const [page, setPage] = useState(1);
  const { data } = useProjects(page);
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / 4));

  function handleStart(projectId: string) {
    console.log("start/pause project:", projectId);
  }

  return (
    <div className="flex h-full flex-col px-6 pb-3 pt-4">
      {/* Top toolbar */}
      <div className="mb-4 flex items-center">
        <button
          onClick={() => openDrawer()}
          className="flex items-center gap-1 rounded-2xl px-5 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90"
          style={{ backgroundColor: "var(--color-brand-500)" }}
        >
          <span>新建项目</span>
          <span className="text-base">+</span>
        </button>

        <div className="ml-auto flex items-center gap-1 text-sm" style={{ color: "var(--color-ink-faint)" }}>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded p-1 transition-colors hover:bg-zinc-100 disabled:opacity-30"
            aria-label="上一页"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          <span className="tabular-nums">
            {page}/{totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded p-1 transition-colors hover:bg-zinc-100 disabled:opacity-30"
            aria-label="下一页"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        </div>
      </div>

      {/* Project grid */}
      <div className="min-h-0 flex-1">
        <ProjectGrid page={page} onStart={handleStart} />
      </div>

      {/* Bottom status bars */}
      <div className="mt-3">
        <StatusBars />
      </div>

      {/* Inception drawer (overlay) */}
      <InceptionDrawer />
    </div>
  );
}

export default HomePage;
