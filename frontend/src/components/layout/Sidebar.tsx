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
    <div className="flex flex-col h-full bg-card border-r border-border">
      {/* Brand */}
      <div className="flex items-center justify-between h-14 px-4 border-b border-border">
        <Link
          href="/"
          className="flex items-center gap-2.5 font-semibold text-foreground overflow-hidden"
          onClick={onCloseMobile}
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shrink-0 shadow-sm">
            <Radio className="h-4 w-4" />
          </div>
          {!collapsed && (
            <span className="text-base tracking-tight truncate font-semibold">
              Social Listening
            </span>
          )}
        </Link>
        {/* Mobile close */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onCloseMobile}
          className="md:hidden h-8 w-8"
          aria-label="Close navigation"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Nav Links */}
      <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map((item) => {
          const active = isItemActive(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onCloseMobile}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all group relative",
                active
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              )}
              title={collapsed ? item.name : undefined}
            >
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0 transition-transform group-hover:scale-105",
                  active ? "text-primary-foreground" : "text-muted-foreground group-hover:text-foreground"
                )}
              />
              {!collapsed && <span className="truncate">{item.name}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Collapse button (desktop only) */}
      <div className="p-2 border-t border-border hidden md:block">
        <Button
          variant="ghost"
          size="sm"
          onClick={onToggleCollapse}
          className="w-full flex items-center justify-center gap-2 text-xs text-muted-foreground hover:text-foreground"
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
          collapsed ? "w-16" : "w-60"
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
          "fixed inset-y-0 left-0 z-50 w-72 bg-card md:hidden transform transition-transform duration-200 ease-in-out shadow-2xl",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {navContent}
      </div>
    </>
  );
}

