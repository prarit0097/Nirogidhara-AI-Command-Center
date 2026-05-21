import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import ErrorBoundary from "@/components/ErrorBoundary";

export function AppLayout() {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  // Phase 14C — re-key the route-level ErrorBoundary on pathname so a
  // crashed boundary on /settings (or anywhere else) resets cleanly when
  // the operator navigates to a different route. Without this, the
  // "Try again" button is the only escape from the error fallback.
  const location = useLocation();
  return (
    <div className="min-h-screen w-full bg-background grid-bg">
      <Sidebar
        open={open}
        onClose={() => setOpen(false)}
        collapsed={collapsed}
        onCollapsedChange={setCollapsed}
      />
      <div className={collapsed ? "lg:pl-[72px] transition-[padding] duration-300" : "lg:pl-[260px] transition-[padding] duration-300"}>
        <Topbar onMenu={() => setOpen(true)} />
        <main className="p-4 sm:p-6 lg:p-10 max-w-[1600px] mx-auto animate-fade-in">
          {/* Phase 14C — global route-level ErrorBoundary around <Outlet/>.
              Any uncaught render error in any child route now surfaces with
              the Topbar + Sidebar chrome intact instead of unmounting the
              entire React root (the prior /settings symptom). The existing
              per-route ErrorBoundary on /saas-admin in App.tsx stays as
              defensive redundancy. */}
          <ErrorBoundary key={location.pathname} sectionName="Page">
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
