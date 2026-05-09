import { type ReactNode } from "react";
import Sidebar from "./Sidebar";
import LogDrawer from "./LogDrawer";
import { useBackendConnection } from "../../hooks/useBackendConnection";

function AppShell({ children }: { children: ReactNode }) {
  const { connected } = useBackendConnection();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <Sidebar connected={connected} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <main className="flex-1 overflow-auto">{children}</main>
        <LogDrawer />
      </div>
    </div>
  );
}

export default AppShell;
