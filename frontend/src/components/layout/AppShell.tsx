import { type ReactNode, useEffect } from "react";
import Sidebar from "./Sidebar";
import LogDrawer from "./LogDrawer";
import ErrorBoundary from "./ErrorBoundary";
import { useBackendConnection } from "../../hooks/useBackendConnection";
import { useThemeStore, applyTheme } from "../../stores/useThemeStore";

function AppShell({ children }: { children: ReactNode }) {
  const { connected } = useBackendConnection();
  const theme = useThemeStore((s) => s.theme);

  // Apply theme on mount
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <Sidebar connected={connected} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <ErrorBoundary>
          <main className="flex-1 overflow-auto">{children}</main>
        </ErrorBoundary>
        <LogDrawer />
      </div>
    </div>
  );
}

export default AppShell;
