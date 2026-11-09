"use client";

import * as React from "react";
import { useEffect, useState, useCallback, useRef } from "react";
import { getHealth } from "@/lib/api";
import { Activity, AlertCircle } from "lucide-react";

export function HealthPill() {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const res = await getHealth();
      setHealthy(res?.status === "ok");
    } catch {
      setHealthy(false);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    check();
    intervalRef.current = setInterval(check, 30000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [check]);

  if (healthy === null) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-muted text-muted-foreground"
        data-testid="health-pill"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-pulse" />
        Checking API…
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border transition-colors ${
        healthy
          ? "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800"
          : "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800"
      }`}
      data-testid="health-pill"
      title={healthy ? "Backend service is responding" : "Backend service is unreachable"}
    >
      <span
        className={`h-2 w-2 rounded-full ${
          healthy ? "bg-emerald-500 animate-pulse" : "bg-rose-500"
        }`}
        aria-hidden="true"
      />
      <span>{healthy ? "API connected" : "API unreachable"}</span>
    </span>
  );
}

