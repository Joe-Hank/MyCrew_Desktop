import { useState } from "react";
import ProjectGrid from "../components/home/ProjectGrid";
import StatusBars from "../components/home/StatusBars";
import InceptionDrawer from "../components/inception/InceptionDrawer";
import PillTabs from "../components/common/PillTabs";
import { useInceptionStore } from "../stores/useInceptionStore";
import { useProjects } from "../queries/useProjectQuery";
import { usePrefsStore, type HomeCategory } from "../stores/usePrefsStore";

function HomePage() {
  const { openDrawer } = useInceptionStore();
  const [page, setPage] = useState(1);
  const category = usePrefsStore((s) => s.homeCategory);
  const setCategory = usePrefsStore((s) => s.setHomeCategory);
  // 2026-05-21: server-side category filter replaces the client-side
  // template_id-prefix hack — totalPages now reflects the filtered count.
  const { data } = useProjects(page, 4, category);
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / 4));

  // Category toggle mirrors TeamPage's PillTabs design (sliding pill +
  // theme-aware active surface). 2026-05-21: 3 categories matching the
  // pivot direction in docs/personal_journey_short.md — Unity stays
  // primary (filter shows existing projects), AI 视频 / PPT 视频 are
  // placeholders that empty out today and fill as new template_id
  // prefixes (`aivideo_*`, `ppt_*`) get added.
  const categoryTabs = [
    { key: "unity" as const, label: "Unity 项目" },
    { key: "ai_video" as const, label: "AI 视频" },
    { key: "ppt" as const, label: "PPT 视频" },
  ];

  return (
    <div className="flex h-full flex-col px-6 pb-3 pt-4">
      {/* Top toolbar */}
      <div className="mb-4 flex items-center gap-3">
        <PillTabs<HomeCategory>
          tabs={categoryTabs}
          active={category}
          onChange={(k) => {
            setCategory(k);
            // Reset pagination when switching category so we don't land
            // on page 3 of a category that only has 1 page of results.
            setPage(1);
          }}
        />
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
        <ProjectGrid page={page} category={category} />
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
