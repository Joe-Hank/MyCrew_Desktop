import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/", label: "主页", icon: "🏠" },
  { to: "/tasks", label: "任务", icon: "📋" },
  { to: "/team", label: "团队", icon: "👥" },
  { to: "/settings", label: "设置", icon: "⚙️" },
] as const;

function Sidebar({ connected }: { connected: boolean }) {
  return (
    <aside className="flex w-[200px] min-w-[200px] flex-col border-r border-zinc-200 bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900">
      {/* Logo */}
      <div className="flex h-14 items-center justify-center border-b border-zinc-200 dark:border-zinc-800">
        <span className="text-lg font-bold tracking-tight">MyCrew</span>
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col gap-0.5 p-2">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-blue-50 font-medium text-blue-600 dark:bg-blue-950/40 dark:text-blue-400"
                  : "text-zinc-600 hover:bg-zinc-200/60 dark:text-zinc-400 dark:hover:bg-zinc-800/60"
              }`
            }
          >
            <span className="text-base">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-zinc-200 p-3 dark:border-zinc-800">
        <div className="flex items-center gap-1.5 text-xs text-zinc-500">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              connected ? "bg-green-500" : "bg-red-500"
            }`}
          />
          <span>{connected ? "后端已连接" : "未连接"}</span>
        </div>
        <div className="mt-1 text-[10px] text-zinc-400">v0.1.0</div>
      </div>
    </aside>
  );
}

export default Sidebar;
