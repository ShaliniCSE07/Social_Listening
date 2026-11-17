"use client";

import * as React from "react";
import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Layers,
  MessageSquare,
  DollarSign,
  CheckCircle2,
  PlusCircle,
  ArrowRight,
  Database,
  Radio,
  Clock,
  ExternalLink,
  ChevronRight,
} from "lucide-react";
import {
  getRuns,
  getSources,
  type RunListItem,
  type SourceConfigItem,
} from "@/lib/api";
import { formatCurrency, formatNumber, formatRelativeTime } from "@/lib/utils";
import StatusBadge from "@/components/StatusBadge";
import ErrorBox from "@/components/ErrorBox";
import EmptyState from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export default function DashboardPage() {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [sources, setSources] = useState<SourceConfigItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [runsData, sourcesData] = await Promise.all([
        getRuns(),
        getSources(),
      ]);
      setRuns(runsData);
      setSources(sourcesData);
    } catch (err: any) {
      setError(err.message || "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Compute stat cards strictly from runs
  const totalRuns = runs.length;
  const totalMentions = runs.reduce(
    (acc, r) => acc + (r.totals?.mentions_count || 0),
    0
  );
  const totalSpend = runs.reduce(
    (acc, r) => acc + (r.totals?.cost_usd || 0),
    0
  );
  const completedRuns = runs.filter(
    (r) => (r.status || "").toLowerCase() === "completed"
  ).length;
  const completionRate =
    totalRuns > 0 ? Math.round((completedRuns / totalRuns) * 100) : 0;

  const recentRuns = runs.slice(0, 5);

  return (
    <div className="space-y-8" data-testid="dashboard-page">
      {/* Top Banner / Welcome */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
            Social Listening Dashboard
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Real-time pipeline analytics, collection runs, and source readiness.
          </p>
        </div>
        <Button asChild size="default" className="shadow-sm">
          <Link href="/runs/new">
            <PlusCircle className="h-4 w-4 mr-2" />
            Start new run
          </Link>
        </Button>
      </div>

      {error && <ErrorBox message={error} onRetry={loadData} />}

      {/* ── 4 Stat Cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Runs */}
        <Card data-testid="stat-total-runs">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Total Runs
            </CardTitle>
            <Layers className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-20" />
            ) : (
              <div className="text-2xl font-bold tabular-nums">
                {formatNumber(totalRuns)}
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-1">
              Historical collection runs
            </p>
          </CardContent>
        </Card>

        {/* Mentions Collected */}
        <Card data-testid="stat-total-mentions">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Total Mentions
            </CardTitle>
            <MessageSquare className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <div className="text-2xl font-bold tabular-nums">
                {formatNumber(totalMentions)}
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-1">
              Gathered across all sources
            </p>
          </CardContent>
        </Card>

        {/* Total Spend */}
        <Card data-testid="stat-total-spend">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Total Spend
            </CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <div className="text-2xl font-bold tabular-nums">
                {formatCurrency(totalSpend)}
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-1">
              API usage and cloud costs
            </p>
          </CardContent>
        </Card>

        {/* Completed Share */}
        <Card data-testid="stat-completion-rate">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Completion Rate
            </CardTitle>
            <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="text-2xl font-bold tabular-nums">
                {completionRate}%
              </div>
            )}
            <p className="text-xs text-muted-foreground mt-1">
              {completedRuns} of {totalRuns} runs completed
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── Main Dashboard Content Grid ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Runs (2 cols) */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Recent Runs</CardTitle>
              <CardDescription>
                Latest social media collection pipelines
              </CardDescription>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href="/runs" className="flex items-center gap-1 text-xs">
                View all
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-16 w-full rounded-lg" />
                ))}
              </div>
            ) : runs.length === 0 ? (
              <EmptyState
                message="No collection runs yet"
                description="Start your first collection run to gather social media mentions across platforms."
                actionHref="/runs/new"
                actionLabel="Start new run"
              />
            ) : (
              <div className="divide-y divide-border">
                {recentRuns.map((run) => (
                  <Link
                    key={run.id}
                    href={`/runs/${run.id}`}
                    className="flex items-center justify-between py-3 px-2 rounded-lg hover:bg-muted/50 transition-colors group"
                  >
                    <div className="space-y-1 min-w-0 pr-4">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-semibold text-primary truncate">
                          {run.id}
                        </span>
                        <StatusBadge status={run.status} />
                      </div>
                      <p className="text-sm font-medium text-foreground truncate">
                        {run.companies.join(", ") || "No companies specified"}
                      </p>
                    </div>

                    <div className="flex items-center gap-4 shrink-0 text-right">
                      <div>
                        <div className="text-sm font-semibold tabular-nums text-foreground">
                          {formatNumber(run.totals?.mentions_count)} mentions
                        </div>
                        <div className="text-xs text-muted-foreground flex items-center justify-end gap-1">
                          <Clock className="h-3 w-3" />
                          <span>{formatRelativeTime(run.created_at)}</span>
                        </div>
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-transform group-hover:translate-x-0.5" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Source Readiness (1 col) */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <div>
              <CardTitle>Source Readiness</CardTitle>
              <CardDescription>
                API and dataset connector statuses
              </CardDescription>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link href="/sources" className="flex items-center gap-1 text-xs">
                Manage
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-12 w-full rounded-lg" />
                ))}
              </div>
            ) : sources.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                No sources configured
              </p>
            ) : (
              <TooltipProvider>
                <div className="space-y-3">
                  {sources.map((s) => {
                    const isReady = s.enabled && s.can_run;
                    return (
                      <div
                        key={s.name}
                        className="flex items-center justify-between p-2.5 rounded-lg border border-border bg-card/60 hover:bg-muted/40 transition-colors"
                      >
                        <div className="min-w-0 pr-2">
                          <div className="flex items-center gap-1.5">
                            <Radio className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <span className="text-sm font-medium text-foreground truncate">
                              {s.name}
                            </span>
                          </div>
                          <span className="text-xs text-muted-foreground capitalize">
                            {s.method} · {s.platforms.join(", ")}
                          </span>
                        </div>

                        {isReady ? (
                          <Badge variant="success" className="shrink-0 text-xs font-normal">
                            Ready
                          </Badge>
                        ) : (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <div className="cursor-help">
                                <Badge variant="warning" className="shrink-0 text-xs font-normal">
                                  Needs setup
                                </Badge>
                              </div>
                            </TooltipTrigger>
                            <TooltipContent side="left">
                              <p className="max-w-xs">{s.reason || "Configuration incomplete"}</p>
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </div>
                    );
                  })}
                </div>
              </TooltipProvider>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
