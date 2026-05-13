import { type ReactNode, useEffect, useState } from "react";
import Sidebar from "./Sidebar";
import LogDrawer from "./LogDrawer";
import ErrorBoundary from "./ErrorBoundary";
import PromptModal from "./PromptModal";
import { useBackendConnection } from "../../hooks/useBackendConnection";
import { useThemeStore, applyTheme } from "../../stores/useThemeStore";

const GRACE_MS = 2_000; // hide banner during initial boot so it doesn't flash

function AppShell({ children }: { children: ReactNode }) {
  const { connected, port } = useBackendConnection();
  const theme = useThemeStore((s) => s.theme);
  const [showBanner, setShowBanner] = useState(false);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Only show the disconnect banner after a short grace period — avoids
  // the red flash on first paint while the port probe is in flight.
  useEffect(() => {
    if (connected) {
      setShowBanner(false);
      return;
    }
    const t = setTimeout(() => setShowBanner(true), GRACE_MS);
    return () => clearTimeout(t);
  }, [connected]);

  return (
    <div
      className="flex h-screen w-screen overflow-hidden"
      style={{
        backgroundColor: "var(--color-surface)",
        color: "var(--color-ink)",
      }}
    >
      <Sidebar connected={connected} />
      <div className="flex flex-1 flex-col overflow-hidden">
        {showBanner && <BackendDownBanner port={port} />}
        <ErrorBoundary>
          <main className="flex-1 overflow-auto">{children}</main>
        </ErrorBoundary>
        <LogDrawer />
      </div>
      <PromptModal />
    </div>
  );
}

function BackendDownBanner({ port }: { port: number | null }) {
  return (
    <div
      className="flex items-center justify-between gap-3 border-b px-4 py-2 text-xs"
      style={{
        backgroundColor: "rgba(239, 68, 68, 0.08)",
        borderColor: "rgba(239, 68, 68, 0.25)",
        color: "var(--color-ink)",
      }}
    >
      <div className="flex items-center gap-2">
        <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
        <span>
          后端未连接{port != null ? `（探测端口 ${port}）` : ""}。已写入的 LLM / MCP 配置仍保存在
          本地数据库；后端恢复后会自动刷新，无需重新填写。
        </span>
      </div>
    </div>
  );
}

export default AppShell;
