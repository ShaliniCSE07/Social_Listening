"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  PlusCircle,
  Layers,
  Database,
  Radio,
  Globe,
  ChevronLeft,
  ChevronRight,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface NavItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "New run", href: "/runs/new", icon: PlusCircle },
  { name: "Runs", href: "/runs", icon: Layers },
  { name: "Sources", href: "/sources", icon: Database },
  { name: "Web Scraper", href: "/scraper", icon: Globe },
];

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({
  collapsed,
  onToggleCollapse,
  mobileOpen,
  onCloseMobile,
}: SidebarProps) {
  const pathname = usePathname();

  const isItemActive = (href: string) => {
    if (href === "/") return pathname === "/";
    if (href === "/runs") return pathname === "/runs";
    if (href === "/runs/new") return pathname === "/runs/new";
    return pathname.startsWith(href);
  };

  const navContent = (
    <div className="flex flex-col h-full bg-sidebar text-sidebar-foreground border-r border-sidebar-border">
      {/* Brand */}
      <div className="flex items-center justify-between h-16 px-4 border-b border-sidebar-border">
        <Link
          href="/"
          className="flex items-center gap-3 overflow-hidden"
          onClick={onCloseMobile}
        >
          <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary via-primary to-highlight text-primary-foreground shrink-0 shadow-lift ring-1 ring-white/10">
            <Radio className="h-4 w-4" />
          </div>
          {!collapsed && (
            <span className="flex flex-col leading-none min-w-0">
              <span className="font-display text-[1.05rem] font-semibold tracking-tight truncate">
                Social Listening
              </span>
              <span className="mt-1 text-[0.65rem] uppercase tracking-[0.18em] text-sidebar-muted truncate">
                Signal desk
              </span>
            </span>
          )}
        </Link>
        {/* Mobile close */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onCloseMobile}
          className="md:hidden h-8 w-8 text-sidebar-muted hover:text-sidebar-foreground hover:bg-sidebar-hover"
          aria-label="Close navigation"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Nav Links */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {!collapsed && <p className="px-3 pb-2 text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-sidebar-muted/80">Workspace</p>}
        {NAV_ITEMS.map((item) => {
          const active = isItemActive(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onCloseMobile}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all group relative",
                active
                  ? "bg-sidebar-active text-sidebar-foreground shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.35)]"
                  : "text-sidebar-muted hover:text-sidebar-foreground hover:bg-sidebar-hover"
              )}
              title={collapsed ? item.name : undefined}
            >
              {active && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-1 rounded-r-full bg-highlight" aria-hidden="true" />
              )}
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0 transition-transform group-hover:scale-105",
                  active ? "text-highlight" : "text-sidebar-muted group-hover:text-sidebar-foreground"
                )}
              />
              {!collapsed && <span className="truncate">{item.name}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Collapse button (desktop only) */}
      <div className="p-3 border-t border-sidebar-border hidden md:block">
        <Button
          variant="ghost"
          size="sm"
          onClick={onToggleCollapse}
          className="w-full flex items-center justify-center gap-2 text-xs text-sidebar-muted hover:text-sidebar-foreground hover:bg-sidebar-hover"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <>
              <ChevronLeft className="h-4 w-4" />
              <span>Collapse</span>
            </>
          )}
        </Button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "hidden md:block transition-all duration-200 shrink-0 select-none z-30 sticky top-0 h-screen",
          collapsed ? "w-[4.5rem]" : "w-64"
        )}
      >
        {navContent}
      </aside>

      {/* Mobile Drawer Backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden animate-in fade-in-0"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      )}

      {/* Mobile Drawer */}
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-72 bg-sidebar md:hidden transform transition-transform duration-200 ease-in-out shadow-2xl",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {navContent}
      </div>
    </>
  );
}

