import * as React from "react";
import {
  Clock,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: string;
  showIcon?: boolean;
  className?: string;
}

const STATUS_CONFIG: Record<
  string,
  {
    bg: string;
    text: string;
    border: string;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    pulse?: boolean;
  }
> = {
  queued: {
    bg: "bg-slate-100 dark:bg-slate-800",
    text: "text-slate-700 dark:text-slate-300",
    border: "border-slate-200 dark:border-slate-700",
    label: "Queued",
    icon: Clock,
  },
  running: {
    bg: "bg-blue-50 dark:bg-blue-950/60",
    text: "text-blue-700 dark:text-blue-300",
    border: "border-blue-200 dark:border-blue-800",
    label: "Running",
    icon: Loader2,
    pulse: true,
  },
  completed: {
    bg: "bg-emerald-50 dark:bg-emerald-950/60",
    text: "text-emerald-700 dark:text-emerald-300",
    border: "border-emerald-200 dark:border-emerald-800",
    label: "Completed",
    icon: CheckCircle2,
  },
  partial: {
    bg: "bg-amber-50 dark:bg-amber-950/60",
    text: "text-amber-700 dark:text-amber-300",
    border: "border-amber-200 dark:border-amber-800",
    label: "Partial",
    icon: AlertTriangle,
  },
  failed: {
    bg: "bg-rose-50 dark:bg-rose-950/60",
    text: "text-rose-700 dark:text-rose-300",
    border: "border-rose-200 dark:border-rose-800",
    label: "Failed",
    icon: XCircle,
  },
};

export default function StatusBadge({
  status,
  showIcon = true,
  className,
}: StatusBadgeProps) {
  const normStatus = (status || "").toLowerCase();
  const cfg = STATUS_CONFIG[normStatus] ?? {
    bg: "bg-slate-100 dark:bg-slate-800",
    text: "text-slate-700 dark:text-slate-300",
    border: "border-slate-200 dark:border-slate-700",
    label: status,
    icon: HelpCircle,
  };

  const Icon = cfg.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border transition-colors",
        cfg.bg,
        cfg.text,
        cfg.border,
        cfg.pulse && "animate-pulse",
        className
      )}
      data-testid="status-badge"
    >
      {showIcon && (
        <Icon
          className={cn(
            "h-3 w-3 shrink-0",
            normStatus === "running" && "animate-spin"
          )}
          aria-hidden="true"
        />
      )}
      <span>{cfg.label}</span>
    </span>
  );
}
