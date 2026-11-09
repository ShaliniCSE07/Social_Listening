"use client";

import * as React from "react";
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useParams } from "next/navigation";
import {
  Copy,
  Check,
  Download,
  Clock,
  RotateCcw,
  AlertTriangle,
  FileText,
  DollarSign,
  Layers,
  MessageSquare,
  Building2,
  Calendar,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Filter,
  Radio,
  SlidersHorizontal,
  Info,
} from "lucide-react";
import {
  getRun,
  getMentions,
  getAttempts,
  getDownloadUrl,
  type RunDetailResponse,
  type CompactMention,
  type CollectionAttemptItem,
} from "@/lib/api";
import {
  formatCurrency,
  formatNumber,
  formatExactDate,
  formatDuration,
} from "@/lib/utils";
import StatusBadge from "@/components/StatusBadge";
import ErrorBox from "@/components/ErrorBox";
import LoadingState from "@/components/LoadingState";
import EmptyState from "@/components/EmptyState";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";

export default function RunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = params.id;

  const [run, setRun] = useState<RunDetailResponse | null>(null);
  const [loadingRun, setLoadingRun] = useState(true);
  const [runError, setRunError] = useState("");

  const [attempts, setAttempts] = useState<CollectionAttemptItem[]>([]);
  const [loadingAttempts, setLoadingAttempts] = useState(false);

  // Mentions tab state
  const [mentions, setMentions] = useState<CompactMention[]>([]);
  const [totalMentions, setTotalMentions] = useState(0);
  const [loadingMentions, setLoadingMentions] = useState(false);
  const [mentionsPage, setMentionsPage] = useState(1);
  const [mentionsPageSize, setMentionsPageSize] = useState(25);
  const [filterCompany, setFilterCompany] = useState("all");
  const [filterPlatform, setFilterPlatform] = useState("all");
  const [filterMethod, setFilterMethod] = useState("all");

  // Selected mention for side drawer
  const [selectedMention, setSelectedMention] = useState<any | null>(null);
  const [copiedId, setCopiedId] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [jsonExpanded, setJsonExpanded] = useState(false);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load run details
  const loadRun = useCallback(async () => {
    try {
      const data = await getRun(runId);
      setRun(data);
      setRunError("");

      // Stop polling when no longer running/queued
      if (data.status !== "queued" && data.status !== "running") {
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
      }
    } catch (err: any) {
      setRunError(err.message || "Failed to load run details");
    } finally {
      setLoadingRun(false);
    }
  }, [runId]);

  // Load attempts
  const loadAttempts = useCallback(async () => {
    setLoadingAttempts(true);
    try {
      const data = await getAttempts(runId);
      setAttempts(data);
    } catch {
      // Non-blocking
    } finally {
      setLoadingAttempts(false);
    }
  }, [runId]);

  // Load mentions
  const loadMentions = useCallback(async () => {
    setLoadingMentions(true);
    try {
      const res = await getMentions(runId, {
        page: mentionsPage,
        page_size: mentionsPageSize,
        company: filterCompany !== "all" ? filterCompany : undefined,
        platform: filterPlatform !== "all" ? filterPlatform : undefined,
        method: filterMethod !== "all" ? filterMethod : undefined,
        full: true,
      });
      setMentions(res.items);
      setTotalMentions(res.total);
    } catch {
      // Non-blocking
    } finally {
      setLoadingMentions(false);
    }
  }, [runId, mentionsPage, mentionsPageSize, filterCompany, filterPlatform, filterMethod]);

  useEffect(() => {
    loadRun();
    loadAttempts();
    loadMentions();

    // Polling every 3s while queued/running
    pollIntervalRef.current = setInterval(() => {
      loadRun();
      loadAttempts();
    }, 3000);

    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [loadRun, loadAttempts, loadMentions]);

  // Copy Run ID
  const handleCopyRunId = () => {
    navigator.clipboard.writeText(runId);
    setCopiedId(true);
    toast.success("Run ID copied to clipboard");
    setTimeout(() => setCopiedId(false), 2000);
  };

  const handleCopyJson = (data: any) => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    setCopiedJson(true);
    toast.success("JSON copied to clipboard");
    setTimeout(() => setCopiedJson(false), 2000);
  };

  // Group attempts by company
  const attemptsByCompany = useMemo(() => {
    const map: Record<string, CollectionAttemptItem[]> = {};
    attempts.forEach((a) => {
      const comp = a.company || "General";
      if (!map[comp]) map[comp] = [];
      map[comp].push(a);
    });
    return map;
  }, [attempts]);

  // Failures count
  const failedAttempts = attempts.filter((a) => (a.status || "").toLowerCase() === "failed");
  const failedCount = failedAttempts.length;

  // Plain-language "What happened" summary
  const whatHappenedReasons = useMemo(() => {
    const reasons: string[] = [];
    if (run?.error) {
      reasons.push(run.error);
    }
    attempts.forEach((a) => {
      if (a.reason && !reasons.includes(a.reason)) {
        reasons.push(a.reason);
      }
    });
    return reasons;
  }, [run?.error, attempts]);

  if (loadingRun && !run) return <LoadingState message="Loading run details…" />;
  if (runError) return <ErrorBox message={runError} onRetry={loadRun} />;
  if (!run) return <ErrorBox message="Run not found" />;

  const isRunning = run.status === "running" || run.status === "queued";
  const budgetSnapshot = run.budget_snapshot || {};
  const spentSoFar = budgetSnapshot.spent_usd ?? run.counts?.cost_usd ?? 0;
  const budgetLimit = budgetSnapshot.limit_usd ?? null;
  const budgetProgress =
    budgetLimit && budgetLimit > 0
      ? Math.min(100, Math.round((spentSoFar / budgetLimit) * 100))
      : 0;

  return (
    <div className="space-y-6" data-testid="run-detail">
      {/* Breadcrumbs */}
      <Breadcrumbs
        items={[
          { label: "Runs", href: "/runs" },
          { label: run.id },
        ]}
      />

      {/* ── Header Card ── */}
      <Card className="shadow-sm">
        <CardContent className="p-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-1.5">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="font-mono text-lg font-bold text-foreground">
                  {run.id}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleCopyRunId}
                  className="h-7 w-7 text-muted-foreground hover:text-foreground"
                  aria-label="Copy run ID"
                >
                  {copiedId ? (
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </Button>
                <StatusBadge status={run.status} />
              </div>

              <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap pt-1">
                <span suppressHydrationWarning>
                  Created: {formatExactDate(run.created_at)}
                </span>
                {run.started_at && (
                  <span suppressHydrationWarning>
                    Started: {formatExactDate(run.started_at)}
                  </span>
                )}
                {run.finished_at && (
                  <span suppressHydrationWarning>
                    Finished: {formatExactDate(run.finished_at)}
                  </span>
                )}
                <span>
                  Duration: {formatDuration(run.started_at, run.finished_at)}
                </span>
              </div>
            </div>

            {/* Download Buttons */}
            <div className="flex items-center gap-2">
              <Button asChild variant="outline" size="sm">
                <a
                  href={getDownloadUrl(run.id, "mentions.jsonl")}
                  download
                  className="flex items-center gap-1.5"
                >
                  <Download className="h-3.5 w-3.5" />
                  Mentions (.jsonl)
                </a>
              </Button>
              <Button asChild variant="outline" size="sm">
                <a
                  href={getDownloadUrl(run.id, "attempts.jsonl")}
                  download
                  className="flex items-center gap-1.5"
                >
                  <Download className="h-3.5 w-3.5" />
                  Attempts (.jsonl)
                </a>
              </Button>
            </div>
          </div>

          {/* Running progress bar indicator */}
          {isRunning && (
            <div className="mt-6 pt-4 border-t border-border space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
                  Pipeline active — collecting live records…
                </span>
                <span>Polling every 3s</span>
              </div>
              <Progress value={undefined} className="h-1.5 bg-blue-100 dark:bg-blue-950" />
            </div>
          )}
        </CardContent>
      </Card>

      {run.error && <ErrorBox message={run.error} />}

      {/* ── Tabs (Overview, Mentions, Attempts, Downloads) ── */}
      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList className="grid w-full sm:w-auto grid-cols-4 sm:inline-flex">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="mentions">
            Mentions ({totalMentions > 0 ? totalMentions : run.counts?.mentions_count || 0})
          </TabsTrigger>
          <TabsTrigger value="attempts">
            Attempts ({attempts.length > 0 ? attempts.length : run.counts?.attempts_count || 0})
          </TabsTrigger>
          <TabsTrigger value="downloads">Downloads</TabsTrigger>
        </TabsList>

        {/* ── OVERVIEW TAB ── */}
        <TabsContent value="overview" className="space-y-6">
          {/* 4 Stat Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Mentions Gathered
                </CardTitle>
                <MessageSquare className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold tabular-nums">
                  {formatNumber(run.counts?.mentions_count)}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Collection Attempts
                </CardTitle>
                <Layers className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold tabular-nums">
                  {formatNumber(run.counts?.attempts_count)}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Failed Attempts
                </CardTitle>
                <AlertTriangle className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold tabular-nums text-rose-600 dark:text-rose-400">
                  {formatNumber(failedCount)}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Total Spend
                </CardTitle>
                <DollarSign className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold tabular-nums">
                  {formatCurrency(run.counts?.cost_usd)}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Budget Card */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Budget Snapshot</CardTitle>
                <CardDescription>
                  Spending consumption and platform breakdown
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="flex items-center justify-between text-sm mb-1">
                    <span className="text-muted-foreground">Spent vs Limit</span>
                    <span className="font-semibold tabular-nums">
                      {formatCurrency(spentSoFar)}{" "}
                      <span className="text-muted-foreground font-normal">
                        / {budgetLimit ? formatCurrency(budgetLimit) : "Unlimited"}
                      </span>
                    </span>
                  </div>
                  {budgetLimit ? (
                    <Progress value={budgetProgress} className="h-2" />
                  ) : (
                    <div className="text-xs text-muted-foreground">
                      No budget cap specified for this run.
                    </div>
                  )}
                </div>

                {budgetSnapshot.platform_costs &&
                  Object.keys(budgetSnapshot.platform_costs).length > 0 && (
                    <div className="pt-3 border-t border-border">
                      <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-2">
                        Spend Per Platform
                      </span>
                      <div className="space-y-2">
                        {Object.entries(budgetSnapshot.platform_costs).map(
                          ([plat, cost]) => (
                            <div
                              key={plat}
                              className="flex items-center justify-between text-sm"
                            >
                              <span className="capitalize text-muted-foreground">
                                {plat}
                              </span>
                              <span className="font-mono tabular-nums font-medium">
                                {formatCurrency(Number(cost))}
                              </span>
                            </div>
                          )
                        )}
                      </div>
                    </div>
                  )}
              </CardContent>
            </Card>

            {/* Sources Card */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Per-Source Results</CardTitle>
                <CardDescription>
                  Item yields and status by collection connector
                </CardDescription>
              </CardHeader>
              <CardContent>
                {Object.keys(run.per_source_results || {}).length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-6">
                    No per-source summaries available yet.
                  </p>
                ) : (
                  <div className="space-y-3">
                    {Object.entries(run.per_source_results).map(([source, data]: [string, any]) => (
                      <div
                        key={source}
                        className="p-3 rounded-lg border border-border bg-card/60 flex items-start justify-between gap-3 text-sm"
                      >
                        <div>
                          <span className="font-medium text-foreground block">
                            {source}
                          </span>
                          {data?.reason && (
                            <span className="text-xs text-muted-foreground mt-0.5 block italic">
                              {data.reason}
                            </span>
                          )}
                        </div>
                        <div className="text-right shrink-0">
                          <span className="font-semibold tabular-nums block">
                            {data?.mentions_count ?? data?.count ?? 0} mentions
                          </span>
                          {data?.status && (
                            <Badge variant="outline" className="text-xs mt-1 capitalize">
                              {data.status}
                            </Badge>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* "What Happened" Callout */}
          {(run.status === "failed" || run.status === "partial" || whatHappenedReasons.length > 0) && (
            <Card className="border-amber-200 dark:border-amber-900 bg-amber-50/50 dark:bg-amber-950/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold flex items-center gap-2 text-amber-800 dark:text-amber-300">
                  <Info className="h-4 w-4" />
                  What happened during collection
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm text-amber-900 dark:text-amber-200">
                {whatHappenedReasons.length === 0 ? (
                  <p>Run completed with status {run.status}.</p>
                ) : (
                  <ul className="list-disc list-inside space-y-1 text-xs">
                    {whatHappenedReasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ── MENTIONS TAB ── */}
        <TabsContent value="mentions" className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-base">Collected Mentions</CardTitle>
                  <CardDescription>
                    Browse and inspect extracted social posts, reviews, and tweets.
                  </CardDescription>
                </div>

                {/* Filters */}
                <div className="flex items-center gap-2 flex-wrap">
                  {/* Company Filter */}
                  {run.companies && run.companies.length > 1 && (
                    <Select value={filterCompany} onValueChange={setFilterCompany}>
                      <SelectTrigger className="w-[130px] h-8 text-xs">
                        <SelectValue placeholder="Company" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All companies</SelectItem>
                        {run.companies.map((c) => (
                          <SelectItem key={c} value={c}>
                            {c}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}

                  {/* Page Size */}
                  <Select
                    value={mentionsPageSize.toString()}
                    onValueChange={(val) => {
                      setMentionsPageSize(parseInt(val));
                      setMentionsPage(1);
                    }}
                  >
                    <SelectTrigger className="w-[100px] h-8 text-xs">
                      <SelectValue placeholder="Page size" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="10">10 / page</SelectItem>
                      <SelectItem value="25">25 / page</SelectItem>
                      <SelectItem value="50">50 / page</SelectItem>
                    </SelectContent>
                  </Select>

                  <Button
                    variant="outline"
                    size="sm"
                    onClick={loadMentions}
                    className="h-8"
                  >
                    <RotateCcw className={`h-3.5 w-3.5 ${loadingMentions ? "animate-spin" : ""}`} />
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {loadingMentions ? (
                <div className="p-6">
                  <LoadingState message="Loading mentions…" />
                </div>
              ) : mentions.length === 0 ? (
                <div className="p-8">
                  <EmptyState
                    message="No mentions gathered for this run"
                    description="Check source configurations and parameters in the Overview or Attempts tab."
                  />
                </div>
              ) : (
                <>
                  <Table data-testid="mentions-table">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">Platform</TableHead>
                        <TableHead className="text-xs">Source</TableHead>
                        <TableHead className="text-xs">Date</TableHead>
                        <TableHead className="text-xs">Text Preview</TableHead>
                        <TableHead className="text-xs">Method</TableHead>
                        <TableHead className="text-xs text-right">Cost</TableHead>
                        <TableHead className="text-xs text-right">Action</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {mentions.map((item, idx) => (
                        <TableRow
                          key={idx}
                          onClick={() => setSelectedMention(item)}
                          className="cursor-pointer hover:bg-muted/60 transition-colors"
                          data-testid={`mention-row-${idx}`}
                        >
                          <TableCell className="capitalize text-xs font-semibold">
                            {item.platform || "—"}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {item.source || "—"}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                            {item.date || "—"}
                          </TableCell>
                          <TableCell className="text-xs text-foreground max-w-md truncate">
                            {item.short_text || item.text || "—"}
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-xs uppercase">
                              {item.method || "api"}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right text-xs tabular-nums text-muted-foreground">
                            {item.cost > 0 ? formatCurrency(item.cost) : "—"}
                          </TableCell>
                          <TableCell className="text-right">
                            {item.url ? (
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="text-primary hover:underline inline-flex items-center"
                                aria-label="Open source URL"
                              >
                                <ExternalLink className="h-3.5 w-3.5" />
                              </a>
                            ) : (
                              <span className="text-muted-foreground text-xs">—</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>

                  {/* Pagination */}
                  <div className="flex items-center justify-between p-4 border-t border-border">
                    <span className="text-xs text-muted-foreground">
                      Showing {mentions.length} of {totalMentions} mentions
                    </span>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setMentionsPage((p) => Math.max(1, p - 1))}
                        disabled={mentionsPage === 1 || loadingMentions}
                      >
                        Previous
                      </Button>
                      <span className="text-xs font-medium text-foreground px-2">
                        Page {mentionsPage}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setMentionsPage((p) => p + 1)}
                        disabled={mentions.length < mentionsPageSize || loadingMentions}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── ATTEMPTS TAB ── */}
        <TabsContent value="attempts" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Collection Attempts</CardTitle>
              <CardDescription>
                Timeline of source queries, request costs, item counts, and status reasons.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {loadingAttempts ? (
                <LoadingState message="Loading collection attempts…" />
              ) : attempts.length === 0 ? (
                <EmptyState
                  message="No attempts recorded yet"
                  description="Attempts appear here as pipeline tasks execute."
                />
              ) : (
                <div className="space-y-6">
                  {Object.entries(attemptsByCompany).map(([company, items]) => (
                    <div key={company} className="space-y-3">
                      <div className="flex items-center gap-2">
                        <Building2 className="h-4 w-4 text-primary" />
                        <h4 className="text-sm font-semibold text-foreground">
                          {company}
                        </h4>
                        <Badge variant="secondary" className="text-xs">
                          {items.length} attempt{items.length !== 1 ? "s" : ""}
                        </Badge>
                      </div>

                      <div className="divide-y divide-border rounded-xl border border-border bg-card overflow-hidden">
                        {items.map((att, i) => (
                          <div
                            key={i}
                            className="p-3.5 hover:bg-muted/40 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-2"
                          >
                            <div className="space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-foreground capitalize">
                                  {att.platform}
                                </span>
                                <Badge variant="outline" className="text-xs uppercase">
                                  {att.method}
                                </Badge>
                                <StatusBadge status={att.status} />
                              </div>
                              {att.reason && (
                                <p className="text-xs text-muted-foreground italic">
                                  {att.reason}
                                </p>
                              )}
                            </div>

                            <div className="flex items-center gap-4 text-xs text-muted-foreground shrink-0 sm:text-right">
                              <div>
                                <span className="font-semibold text-foreground tabular-nums">
                                  {formatNumber(att.mentions_count)}
                                </span>{" "}
                                mentions
                              </div>
                              <div>
                                Cost:{" "}
                                <span className="font-semibold text-foreground tabular-nums">
                                  {formatCurrency(att.cost_usd)}
                                </span>
                              </div>
                              {att.duration_sec != null && (
                                <div>{att.duration_sec.toFixed(1)}s</div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── DOWNLOADS TAB ── */}
        <TabsContent value="downloads" className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="h-4 w-4 text-primary" />
                    mentions.jsonl
                  </CardTitle>
                  <Button asChild size="sm">
                    <a
                      href={getDownloadUrl(run.id, "mentions.jsonl")}
                      download
                      className="flex items-center gap-1.5"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download
                    </a>
                  </Button>
                </div>
                <CardDescription>
                  Full raw mention records gathered across all platforms in newline-delimited JSON format.
                </CardDescription>
              </CardHeader>
              <CardContent className="text-xs text-muted-foreground">
                Total mentions: {formatNumber(run.counts?.mentions_count)} records.
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="h-4 w-4 text-primary" />
                    attempts.jsonl
                  </CardTitle>
                  <Button asChild size="sm">
                    <a
                      href={getDownloadUrl(run.id, "attempts.jsonl")}
                      download
                      className="flex items-center gap-1.5"
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download
                    </a>
                  </Button>
                </div>
                <CardDescription>
                  Diagnostic log of collection attempts, connector statuses, error reasons, and costs.
                </CardDescription>
              </CardHeader>
              <CardContent className="text-xs text-muted-foreground">
                Total attempts: {formatNumber(run.counts?.attempts_count)} records.
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      {/* ── Mention Detail Dialog (Side Drawer) ── */}
      <Dialog
        open={!!selectedMention}
        onOpenChange={(open) => !open && setSelectedMention(null)}
      >
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="mention-detail-drawer">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <span className="capitalize">{selectedMention?.platform || "Mention"}</span> Record
            </DialogTitle>
            <DialogDescription>
              Detailed payload and extracted metadata fields.
            </DialogDescription>
          </DialogHeader>

          {selectedMention && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 p-3 rounded-lg border border-border bg-muted/30 text-xs">
                <div>
                  <span className="text-muted-foreground block">Platform</span>
                  <span className="font-semibold text-foreground capitalize">
                    {selectedMention.platform || "—"}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Source Connector</span>
                  <span className="font-semibold text-foreground">
                    {selectedMention.source || "—"}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Collection Date</span>
                  <span className="font-semibold text-foreground">
                    {selectedMention.date || "—"}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Collection Method</span>
                  <span className="font-semibold text-foreground uppercase">
                    {selectedMention.method || "—"}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Cost</span>
                  <span className="font-semibold text-foreground tabular-nums">
                    {formatCurrency(selectedMention.cost)}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground block">External URL</span>
                  {selectedMention.url ? (
                    <a
                      href={selectedMention.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary hover:underline inline-flex items-center gap-1"
                    >
                      Visit link <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : (
                    <span>—</span>
                  )}
                </div>
              </div>

              {/* Full Text Content */}
              <div>
                <span className="text-xs font-semibold text-muted-foreground block mb-1">
                  Text Content
                </span>
                <div className="p-3 rounded-lg border border-border bg-card whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                  {selectedMention.text || selectedMention.short_text || "No text content recorded."}
                </div>
              </div>

              {/* Collapsible Raw JSON Block */}
              <div className="pt-2 border-t border-border">
                <div className="flex items-center justify-between mb-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setJsonExpanded(!jsonExpanded)}
                    className="text-xs h-7 px-2"
                  >
                    {jsonExpanded ? (
                      <>
                        <ChevronUp className="h-3.5 w-3.5 mr-1" />
                        Hide raw JSON payload
                      </>
                    ) : (
                      <>
                        <ChevronDown className="h-3.5 w-3.5 mr-1" />
                        View raw JSON payload
                      </>
                    )}
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => handleCopyJson(selectedMention)}
                    className="text-xs h-7"
                    data-testid="copy-json-btn"
                  >
                    {copiedJson ? (
                      <>
                        <Check className="h-3.5 w-3.5 mr-1 text-emerald-500" />
                        Copied
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5 mr-1" />
                        Copy JSON
                      </>
                    )}
                  </Button>
                </div>

                {jsonExpanded && (
                  <pre
                    className="p-3 rounded-lg border border-border bg-muted/60 text-xs overflow-x-auto max-h-60 font-mono"
                    data-testid="raw-json-block"
                  >
                    {JSON.stringify(selectedMention, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
