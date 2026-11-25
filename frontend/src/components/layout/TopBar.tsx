"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeProvider";
import { HealthPill } from "./HealthPill";

interface TopBarProps {
  onOpenMobile: () => void;
}

function getPageTitle(pathname: string): string {
  if (pathname === "/") return "Dashboard";
  if (pathname === "/runs/new") return "New Collection Run";
  if (pathname === "/runs") return "Collection Runs";
  if (pathname.startsWith("/runs/")) return "Run Details";
  if (pathname === "/sources") return "Source Integrations";
  if (pathname === "/scraper") return "Web Scraper";
  return "Social Listening";
}

export function TopBar({ onOpenMobile }: TopBarProps) {
  const pathname = usePathname();
  const title = getPageTitle(pathname);

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-border/70 bg-background/75 backdrop-blur-md px-4 sm:px-6 lg:px-8">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={onOpenMobile}
          className="md:hidden h-8 w-8"
          aria-label="Open navigation drawer"
        >
          <Menu className="h-5 w-5" />
        </Button>
        <h1 className="eyebrow !text-[0.72rem] text-foreground/70">
          {title}
        </h1>
      </div>

      <div className="flex items-center gap-3">
        <HealthPill />
        <ThemeToggle />
      </div>
    </header>
  );
}

