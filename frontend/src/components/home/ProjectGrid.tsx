import { useState } from "react";
import { useProjects } from "../../queries/useProjectQuery";
import ProjectCard from "./ProjectCard";

function ProjectGrid({ onStart }: { onStart: (id: string) => void }) {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useProjects(page);

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / 4);

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 p-4">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="h-40 animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
          />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-zinc-400">
        <p className="mb-2 text-lg">还没有项目</p>
        <p className="text-sm">点击「新建项目」开始你的第一个项目</p>
      </div>
    );
  }

  return (
    <div>
      <div className="grid grid-cols-2 gap-4 p-4">
        {items.map((project) => (
          <ProjectCard key={project.id} project={project} onStart={onStart} />
        ))}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pb-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border border-zinc-300 px-3 py-1 text-xs disabled:opacity-50 dark:border-zinc-600"
          >
            上一页
          </button>
          <span className="text-xs text-zinc-500">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded border border-zinc-300 px-3 py-1 text-xs disabled:opacity-50 dark:border-zinc-600"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}

export default ProjectGrid;
