import { NavLink } from "react-router-dom";
import { useEffect } from "react";
import { useThemeStore, applyTheme } from "../../stores/useThemeStore";

const navItems = [
  { to: "/", label: "首页" },
  { to: "/tasks", label: "任务" },
  { to: "/team", label: "团队" },
  { to: "/settings", label: "设置" },
] as const;

function Sidebar({ connected }: { connected: boolean }) {
  return (
    <aside
      className="flex w-[110px] min-w-[110px] flex-col bg-white dark:bg-[var(--color-card)]"
      style={{ borderRight: "1px solid var(--color-border-soft)" }}
    >
      {/* Logo */}
      <div className="flex h-16 items-center justify-center pt-2">
        <span
          className="text-xl font-bold tracking-tight"
          style={{ color: "var(--color-ink-strong)" }}
        >
          MyCrew
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col items-stretch gap-1 px-2 pt-6">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `flex items-center justify-center rounded-md py-2.5 text-base font-semibold transition-colors ${
                isActive ? "text-[var(--color-brand-500)]" : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink-label)]"
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* Bottom: Theme toggle + version chip + connection dot */}
      <div className="flex flex-col items-center gap-2 px-2 pb-3">
        <ThemeToggle />
        <div
          className="flex h-7 w-[72px] items-center justify-center rounded-full border text-[11px]"
          style={{
            borderColor: "var(--color-border-strong)",
            color: "var(--color-ink-ghost)",
            backgroundColor: "var(--color-card)",
          }}
        >
          v0.3
        </div>
        <div
          className="flex items-center gap-1"
          title={connected ? "后端已连接" : "未连接"}
        >
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              connected ? "bg-green-500" : "bg-red-500"
            }`}
          />
        </div>
      </div>
    </aside>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useThemeStore();

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const isLight = theme === "light";

  return (
    <button
      onClick={toggle}
      title={`切换主题：${isLight ? "→ 深色" : "→ 浅色"}`}
      className="relative flex h-9 w-[72px] items-center rounded-full p-1 transition-colors"
      style={{ backgroundColor: "var(--color-surface-alt)" }}
    >
      {/* 滑块 */}
      <div
        className="absolute top-1 h-7 w-[30px] rounded-full bg-white shadow-sm transition-transform duration-200"
        style={{
          transform: isLight ? "translateX(0)" : "translateX(32px)",
        }}
      />
      {/* Sun icon */}
      <div className="relative z-10 flex h-7 w-[30px] items-center justify-center">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={isLight ? "var(--color-ink)" : "var(--color-ink-disabled)"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
      </div>
      {/* Moon icon */}
      <div className="relative z-10 flex h-7 w-[30px] items-center justify-center">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={isLight ? "var(--color-ink-disabled)" : "var(--color-ink)"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      </div>
    </button>
  );
}

export default Sidebar;
