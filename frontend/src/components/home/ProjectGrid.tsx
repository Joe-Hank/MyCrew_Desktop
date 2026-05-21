import { useProjects } from "../../queries/useProjectQuery";
import type { HomeCategory } from "../../stores/usePrefsStore";
import ProjectCard from "./ProjectCard";

// 2026-05-21: category filtering moved server-side (`?category=ai_video`)
// after migration 0023 added `projects.category`. ProjectGrid no longer
// needs the client-side template_id-prefix matcher — `useProjects` here
// only ensures the query's cache key includes the category, so a Tab
// switch refetches instead of showing the previous bucket's data.

function ProjectGrid({ page, category }: { page: number; category: HomeCategory }) {
  const { data, isLoading } = useProjects(page, 4, category);
  const items = data?.items ?? [];

  if (isLoading) {
    return (
      <div className="grid h-full auto-rows-fr grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="animate-pulse rounded-[10px]"
            style={{ backgroundColor: "var(--color-surface-alt)" }}
          />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    const emptyCopy: Record<HomeCategory, { title: string; hint: string }> = {
      unity: {
        title: "还没有 Unity 项目",
        hint: "点击「新建项目」开始你的第一个 Unity 项目",
      },
      ai_video: {
        title: "还没有 AI 视频项目",
        hint: "AI 漫剧剧本生成等场景，点击「新建项目」开始",
      },
      ppt: {
        title: "还没有 PPT 视频项目",
        hint: "自动化 PPT 制作场景，点击「新建项目」开始",
      },
    };
    const { title, hint } = emptyCopy[category];
    return (
      <div
        className="flex h-full flex-col items-center justify-center"
        style={{ color: "var(--color-ink-ghost)" }}
      >
        <p className="mb-2 text-base">{title}</p>
        <p className="text-sm">{hint}</p>
      </div>
    );
  }

  return (
    <div className="grid h-full auto-rows-fr grid-cols-4 gap-4">
      {items.map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
      {items.length < 4 &&
        Array.from({ length: 4 - items.length }).map((_, i) => (
          <div key={`empty-${i}`} />
        ))}
    </div>
  );
}

export default ProjectGrid;
