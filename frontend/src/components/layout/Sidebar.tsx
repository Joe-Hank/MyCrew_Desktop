import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/", label: "主页", icon: "🏠" },
  { to: "/tasks", label: "任务", icon: "📋" },
  { to: "/team", label: "团队", icon: "👥" },
  { to: "/settings", label: "设置", icon: "⚙️" },
] as const;

function Sidebar() {
  return (
    <aside className="flex w-[200px] flex-col border-r border-zinc-200 bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex h-14 items-center justify-center border-b border-zinc-200 text-lg font-bold dark:border-zinc-800">
        MyCrew
      </div>

      <nav className="flex flex-1 flex-col gap-1 p-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-zinc-200 font-medium dark:bg-zinc-800"
                  : "hover:bg-zinc-200/60 dark:hover:bg-zinc-800/60"
              }`
            }
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-zinc-200 p-3 text-xs text-zinc-500 dark:border-zinc-800">
        v0.1.0
      </div>
    </aside>
  );
}

export default Sidebar;
