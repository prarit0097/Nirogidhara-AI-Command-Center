import { useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppLayout() {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
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
          <Outlet />
        </main>
      </div>
    </div>
  );
}
