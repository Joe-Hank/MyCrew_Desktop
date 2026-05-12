import { useProjects } from "../../queries/useProjectQuery";
import ProjectCard from "./ProjectCard";

function ProjectGrid({
  page,
  onStart,
}: {
  page: number;
  onStart: (id: string) => void;
}) {
  const { data, isLoading } = useProjects(page);

  const items = data?.items ?? [];

  if (isLoading) {
    return (
      <div className="grid h-full grid-cols-4 gap-4">
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
    return (
      <div
        className="flex h-full flex-col items-center justify-center"
        style={{ color: "var(--color-ink-ghost)" }}
      >
        <p className="mb-2 text-base">还没有项目</p>
        <p className="text-sm">点击「新建项目」开始你的第一个项目</p>
      </div>
    );
  }

  return (
    <div className="grid h-full grid-cols-4 gap-4">
      {items.map((project) => (
        <ProjectCard key={project.id} project={project} onStart={onStart} />
      ))}
      {items.length < 4 &&
        Array.from({ length: 4 - items.length }).map((_, i) => (
          <div key={`empty-${i}`} />
        ))}
    </div>
  );
}

export default ProjectGrid;
