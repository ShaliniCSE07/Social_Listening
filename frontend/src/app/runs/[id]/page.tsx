"use client";

import * as React from "react";
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useParams } from "next/navigation";
import {
  Copy,
  Check,
  CheckCircle2,
  XCircle,
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
  X,
} from "lucide-react";
import {
  getRun,
  getMentions,
  getAttempts,
  getDownloadUrl,
  type RunDetailResponse,
  type CompactMention,
  type CollectionAttemptItem,
  type TaskOutcomeItem,
  type InvalidCompanyItem,
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
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
  const [htmlExpanded, setHtmlExpanded] = useState(false);
  const [copiedHtml, setCopiedHtml] = useState(false);

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
      setAttempts(Array.isArray(data) ? data : []);
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
      setMentions(Array.isArray(res?.items) ? res.items : []);
      setTotalMentions(res?.total || 0);
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

  const handleCopyRawHtml = (rawHtml: string) => {
    navigator.clipboard.writeText(rawHtml);
    setCopiedHtml(true);
    toast.success("Original HTML copied to clipboard");
    setTimeout(() => setCopiedHtml(false), 2000);
  };

  // Check if scraping returned mentions to display privacy notice
  const hasScrapedMentions = useMemo(() => {
    const inMentions = (mentions || []).some(
      (m) => (m?.method || m?.method_used || "").toLowerCase() === "scraping"
    );
    if (inMentions) return true;
    const inAttempts = (attempts || []).some(
      (a) =>
        (a?.method || "").toLowerCase() === "scraping" &&
        ((a?.mentions_count ?? 0) > 0 || ((a as any)?.item_count ?? 0) > 0)
    );
    if (inAttempts) return true;
    const perSource = run?.per_source_results || {};
    for (const [srcName, res] of Object.entries(perSource)) {
      if (srcName.toLowerCase().includes("scraping")) {
        const count = (res as any)?.mentions_count ?? (res as any)?.count ?? 0;
        if (count > 0) return true;
      }
    }
    return false;
  }, [mentions, attempts, run]);

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

  // Helper to format connector names for display
  const formatConnectorName = (name: string): string => {
    if (!name) return "";
    const lower = name.toLowerCase();
    if (lower === "reddit_api") return "Reddit API";
    if (lower === "google_places") return "Google Places";
    if (lower === "google_business_profile") return "Google Business Profile";
    if (lower === "twitter_api") return "Twitter API";
    if (lower === "dataset") return "Dataset";
    if (lower === "scraping") return "Web Scraping";
    if (lower === "third_party_reddit") return "Third-Party Reddit";
    if (lower === "third_party_reviews") return "Third-Party Reviews";
    return name
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  };

  // Helper to format fallback chain (e.g. "Reddit API failed, then Dataset")
  const formatFallbackChain = (fallbackPath: string[] = [], status?: string): string => {
    if (!fallbackPath || fallbackPath.length === 0) {
      return "Direct";
    }
    if (fallbackPath.length === 1) {
      const formatted = formatConnectorName(fallbackPath[0]);
      return (status || "").toLowerCase() === "failed" ? `${formatted} failed` : formatted;
    }
    const failedSegments = fallbackPath
      .slice(0, -1)
      .map(formatConnectorName)
      .map((name) => `${name} failed`)
      .join(", ");
    const lastSegment = formatConnectorName(fallbackPath[fallbackPath.length - 1]);
    return `${failedSegments}, then ${lastSegment}`;
  };

  // Helper to get remediation hints for known reasons
  const getHintForReason = (reason: string, platform?: string): string | null => {
    if (!reason) return null;
    const r = reason.toLowerCase();
    const p = (platform || "").toLowerCase();

    if (
      r.includes("reddit") &&
      (r.includes("credential") || r.includes("missing") || r.includes("token") || r.includes("secret"))
    ) {
      return "Add Reddit credentials in .env, or choose a dataset.";
    }
    if (
      (r.includes("google") || p.includes("google")) &&
      (r.includes("credential") || r.includes("key") || r.includes("missing") || r.includes("places") || r.includes("denied"))
    ) {
      return "Add Google Places API key in .env, or choose a dataset.";
    }
    if (r.includes("budget") || r.includes("exhausted") || r.includes("exceeds")) {
      return "Increase run budget limit in Options, or choose free connectors.";
    }
    if (r.includes("stale") || r.includes("older than") || r.includes("max age") || r.includes("fresh")) {
      return "Adjust max age days or uncheck Require Fresh in Options.";
    }
    if (r.includes("scraping") && (r.includes("not allowed") || r.includes("condition"))) {
      return "Enable scraping or check domain permissions.";
    }
    if (r.includes("no eligible method")) {
      if (r.includes("reddit") || p.includes("reddit")) {
        return "Add Reddit credentials in .env, or choose a dataset.";
      }
      if (r.includes("google") || p.includes("google")) {
        return "Add Google Places API key in .env, or choose a dataset.";
      }
      return "Add required credentials in .env, or choose a dataset.";
    }
    return null;
  };

  // Structured failed tasks list for "What happened" card
  const failedTasksList = useMemo(() => {
    if (!run) return [];
    const list: Array<{
      company: string;
      platform: string;
      reason: string;
      hint: string | null;
    }> = [];
    const seenKeys = new Set<string>();

    // 1. From task_outcomes if available
    if (run.task_outcomes && run.task_outcomes.length > 0) {
      const failedOutcomes = run.task_outcomes.filter((t) => (t.status || "").toLowerCase() === "failed");
      for (const t of failedOutcomes) {
        const taskKey = `${t.company}::${t.platform}`.toLowerCase();
        let reason = "";

        // Match decision summary or rejection reason
        const dec = (run.decisions || []).find(
          (d) =>
            d.task?.company?.toLowerCase() === t.company?.toLowerCase() &&
            (d.task?.platform?.toLowerCase() === t.platform?.toLowerCase() ||
              String(d.task?.platform) === String(t.platform))
        );
        if (dec) {
          reason = dec.summary || (dec.rejected && dec.rejected.map((r) => r.reason).join("; ")) || "";
        }

        // Match attempt reason
        if (!reason) {
          const att = attempts.find(
            (a) =>
              a.company?.toLowerCase() === t.company?.toLowerCase() &&
              (a.platform?.toLowerCase() === t.platform?.toLowerCase() ||
                String(a.platform).toLowerCase() === t.platform?.toLowerCase()) &&
              (a.status || "").toLowerCase() === "failed"
          );
          if (att?.reason) reason = att.reason;
          else if (att?.error) reason = att.error;
        }

        if (!reason && run.error) {
          reason = run.error;
        }
        if (!reason) {
          reason = `Collection task failed for ${t.company} on ${t.platform}.`;
        }

        seenKeys.add(taskKey);
        list.push({
          company: t.company,
          platform: t.platform,
          reason,
          hint: getHintForReason(reason, t.platform),
        });
      }
    }

    // 2. From failed attempts if not captured in task_outcomes
    attempts.forEach((a) => {
      if ((a.status || "").toLowerCase() === "failed" && a.company && a.platform) {
        const taskKey = `${a.company}::${a.platform}`.toLowerCase();
        if (!seenKeys.has(taskKey)) {
          seenKeys.add(taskKey);
          const reason = a.reason || a.error || run.error || "Collection attempt failed";
          list.push({
            company: a.company,
            platform: a.platform,
            reason,
            hint: getHintForReason(reason, a.platform),
          });
        }
      }
    });

    // 3. If run.error is present and not already in list, include it
    if (run.error && !list.some((item) => item.reason === run.error)) {
      list.push({
        company: run.companies?.[0] || "Pipeline",
        platform: "general",
        reason: run.error,
        hint: getHintForReason(run.error),
      });
    }

    // 4. Fallback if run failed but no error or attempts were recorded
    if (list.length === 0 && run.status === "failed") {
      list.push({
        company: run.companies?.[0] || "Pipeline",
        platform: "all",
        reason: "Pipeline collection failed.",
        hint: null,
      });
    }

    return list;
  }, [run, attempts]);

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

      {/* ── Privacy Notice Card (only when scraping returned mentions) ── */}
      {hasScrapedMentions && (
        <Card className="border-blue-200 dark:border-blue-900 bg-blue-50/60 dark:bg-blue-950/30 shadow-sm" data-testid="privacy-notice-card">
          <CardContent className="p-4 flex items-start gap-3">
            <Info className="h-4 w-4 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
            <div className="text-xs text-blue-900 dark:text-blue-200 space-y-0.5">
              <span className="font-semibold block">Privacy Notice</span>
              <p>
                Scraped content can include usernames. Personal details are masked in the processing step before sharing.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

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

      {/* ── Invalid Companies Warning Box ── */}
      {run.invalid_companies && run.invalid_companies.length > 0 && (
        <Card data-testid="invalid-companies-box" className="border-amber-300 dark:border-amber-900 bg-amber-50/70 dark:bg-amber-950/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold flex items-center gap-2 text-amber-800 dark:text-amber-300">
              <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
              Invalid Companies ({run.invalid_companies.length})
            </CardTitle>
            <CardDescription className="text-xs text-amber-700/90 dark:text-amber-400/90">
              The following companies could not be processed due to validation errors.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-1.5 text-xs text-amber-900 dark:text-amber-200">
            <ul className="space-y-1 list-disc list-inside">
              {run.invalid_companies.map((inv, idx) => (
                <li key={idx}>
                  <span className="font-semibold">{inv.name}</span>:{" "}
                  <span>{Array.isArray(inv.reasons) ? inv.reasons.join(", ") : String(inv.reasons)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* ── "What happened" List (replacing the single red error box) ── */}
      {failedTasksList.length > 0 && (
        <Card data-testid="what-happened-list" className="border-rose-200 dark:border-rose-900 bg-rose-50/50 dark:bg-rose-950/20">
          <div data-testid="error-box">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold flex items-center gap-2 text-rose-900 dark:text-rose-200">
                <AlertTriangle className="h-4 w-4 text-rose-600 dark:text-rose-400" />
                What happened
              </CardTitle>
              <CardDescription className="text-xs text-rose-700/80 dark:text-rose-300/80">
                Review collection task failures and remediation hints.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <ul className="space-y-2.5 divide-y divide-rose-200/50 dark:divide-rose-900/50">
                {failedTasksList.map((item, idx) => (
                  <li key={idx} className={`text-xs space-y-1 ${idx > 0 ? "pt-2.5" : ""}`} data-testid={`failed-task-${idx}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <span className="font-semibold text-rose-900 dark:text-rose-100">
                          {item.company}
                        </span>
                        {item.platform && item.platform !== "all" && item.platform !== "general" && (
                          <Badge variant="outline" className="ml-1.5 border-rose-300 dark:border-rose-800 text-rose-800 dark:text-rose-300 text-[10px] capitalize">
                            {item.platform}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <p className="text-rose-800 dark:text-rose-200 font-medium">
                      {item.reason}
                    </p>
                    {item.hint && (
                      <p className="text-muted-foreground text-[11px] italic pl-2 border-l-2 border-rose-400 dark:border-rose-600">
                        Hint: {item.hint}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </div>
        </Card>
      )}

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

          {/* "How each source was collected" Card */}
          {run.task_outcomes && run.task_outcomes.length > 0 && (
            <Card data-testid="how-each-source-collected-card">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Layers className="h-4 w-4 text-primary" />
                  How each source was collected
                </CardTitle>
                <CardDescription>
                  Collection methods, fallback execution chains, and item yields per task.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {run.task_outcomes.map((t, idx) => {
                    const statusLower = (t.status || "").toLowerCase();
                    return (
                      <div
                        key={idx}
                        data-testid={`task-outcome-row-${idx}`}
                        className="p-3 rounded-lg border border-border bg-card/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs"
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-sm text-foreground">
                              {t.company}
                            </span>
                            <Badge variant="outline" className="text-xs capitalize">
                              {t.platform}
                            </Badge>
                            {statusLower === "ok" && (
                              <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border-emerald-200 hover:bg-emerald-100 flex items-center gap-1 text-[11px]" data-testid="task-status-ok">
                                <CheckCircle2 className="h-3 w-3" />
                                ok
                              </Badge>
                            )}
                            {statusLower === "partial" && (
                              <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 border-amber-200 hover:bg-amber-100 flex items-center gap-1 text-[11px]" data-testid="task-status-partial">
                                <AlertTriangle className="h-3 w-3" />
                                partial
                              </Badge>
                            )}
                            {statusLower === "failed" && (
                              <Badge className="bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300 border-rose-200 hover:bg-rose-100 flex items-center gap-1 text-[11px]" data-testid="task-status-failed">
                                <XCircle className="h-3 w-3" />
                                failed
                              </Badge>
                            )}
                          </div>

                          <div className="space-y-0.5 text-muted-foreground">
                            <div>
                              <span className="font-medium text-foreground">Chosen method: </span>
                              <span>{t.chosen_method ? formatConnectorName(t.chosen_method) : "None"}</span>
                            </div>
                            <div data-testid={`fallback-chain-${idx}`}>
                              <span className="font-medium text-foreground">Fallback path: </span>
                              <span className="font-mono text-[11px] text-foreground/90">
                                {formatFallbackChain(t.fallback_path, t.status)}
                              </span>
                            </div>
                          </div>

                          {/* Scraping evaluation checks if considered or used */}
                          {(() => {
                            const isScrapingChosen = (t.chosen_method || "").toLowerCase() === "scraping";
                            const isScrapingInFallback = (t.fallback_path || []).some((m) => m.toLowerCase().includes("scraping"));
                            const matchingScrapingAttempt = attempts.find(
                              (a) =>
                                (a.method || "").toLowerCase() === "scraping" &&
                                (a.company?.toLowerCase() === t.company?.toLowerCase() || !a.company) &&
                                (a.platform?.toLowerCase() === t.platform?.toLowerCase() || !a.platform || a.platform === "other")
                            );
                            const consideredScraping = isScrapingChosen || isScrapingInFallback || !!matchingScrapingAttempt;

                            if (!consideredScraping) return null;

                            const isSkipped = matchingScrapingAttempt?.status === "skipped";
                            const checks = matchingScrapingAttempt?.scraping_checks;

                            return (
                              <div className="pt-2 mt-2 border-t border-border/50 space-y-2" data-testid={`scraping-details-${idx}`}>
                                <div className="flex items-center justify-between flex-wrap gap-1">
                                  <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                                    Web scraping evaluation
                                  </span>
                                  {isSkipped && (
                                    <span className="text-[11px] font-medium text-amber-600 dark:text-amber-400" data-testid="scraping-skipped-reason">
                                      Skipped: {matchingScrapingAttempt?.reason || "Conditions not met"}
                                    </span>
                                  )}
                                </div>

                                {/* Three checks rows */}
                                <div className="space-y-1 pl-1 text-[11px]">
                                  {/* 1. Site policy allows */}
                                  {(() => {
                                    const val = checks?.site_policy_allows;
                                    const reason = val === true
                                      ? "Site policy permits scraping for this domain"
                                      : val === false
                                      ? "Site policy disallows scraping for this domain"
                                      : "Site policy check not evaluated";
                                    return (
                                      <div className="flex items-center gap-2" data-testid="check-site-policy">
                                        {val === true ? (
                                          <CheckCircle2 className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0" />
                                        ) : val === false ? (
                                          <XCircle className="h-3 w-3 text-destructive shrink-0" />
                                        ) : (
                                          <span className="font-mono text-muted-foreground w-3 text-center shrink-0">-</span>
                                        )}
                                        <span className="font-medium text-foreground">Site policy allows:</span>
                                        <span className="text-muted-foreground">{reason}</span>
                                      </div>
                                    );
                                  })()}

                                  {/* 2. Other methods failed */}
                                  {(() => {
                                    const val = checks?.other_methods_failed;
                                    const reason = val === true
                                      ? (matchingScrapingAttempt?.reason?.includes("no other method available") ? "No other method available" : "Prior collection methods failed or empty")
                                      : val === false
                                      ? "A prior collection method succeeded"
                                      : "Other methods status not evaluated";
                                    return (
                                      <div className="flex items-center gap-2" data-testid="check-other-methods">
                                        {val === true ? (
                                          <CheckCircle2 className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0" />
                                        ) : val === false ? (
                                          <XCircle className="h-3 w-3 text-destructive shrink-0" />
                                        ) : (
                                          <span className="font-mono text-muted-foreground w-3 text-center shrink-0">-</span>
                                        )}
                                        <span className="font-medium text-foreground">Other methods failed:</span>
                                        <span className="text-muted-foreground">{reason}</span>
                                      </div>
                                    );
                                  })()}

                                  {/* 3. Below min threshold */}
                                  {(() => {
                                    const val = checks?.below_min_threshold;
                                    const reason = val === true
                                      ? "Collected items are below the minimum threshold"
                                      : val === false
                                      ? "Collected items already meet or exceed the threshold"
                                      : "Threshold check not evaluated";
                                    return (
                                      <div className="flex items-center gap-2" data-testid="check-below-threshold">
                                        {val === true ? (
                                          <CheckCircle2 className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0" />
                                        ) : val === false ? (
                                          <XCircle className="h-3 w-3 text-destructive shrink-0" />
                                        ) : (
                                          <span className="font-mono text-muted-foreground w-3 text-center shrink-0">-</span>
                                        )}
                                        <span className="font-medium text-foreground">Below minimum threshold:</span>
                                        <span className="text-muted-foreground">{reason}</span>
                                      </div>
                                    );
                                  })()}
                                </div>

                                {/* Execution metrics if attempt ran */}
                                {!isSkipped && (
                                  (matchingScrapingAttempt?.pages_fetched !== undefined ||
                                   matchingScrapingAttempt?.pages_from_cache !== undefined ||
                                   matchingScrapingAttempt?.delay_used !== undefined) && (
                                    <div className="flex items-center gap-4 text-[11px] text-muted-foreground pt-1 flex-wrap border-t border-border/30" data-testid="scraping-run-metrics">
                                      {matchingScrapingAttempt?.pages_fetched !== undefined && (
                                        <span>Pages fetched: <strong className="text-foreground">{matchingScrapingAttempt.pages_fetched}</strong></span>
                                      )}
                                      {matchingScrapingAttempt?.pages_from_cache !== undefined && (
                                        <span>Pages from cache: <strong className="text-foreground">{matchingScrapingAttempt.pages_from_cache}</strong></span>
                                      )}
                                      {matchingScrapingAttempt?.delay_used !== undefined && (
                                        <span>Delay used: <strong className="text-foreground">{matchingScrapingAttempt.delay_used}s</strong></span>
                                      )}
                                    </div>
                                  )
                                )}
                              </div>
                            );
                          })()}
                        </div>

                        <div className="text-right sm:self-center shrink-0">
                          <span className="font-semibold text-sm tabular-nums block text-foreground">
                            {formatNumber(t.items ?? t.total_items ?? 0)} items
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}

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
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {(item.method === "scraping" || item.method_used === "scraping") ? (
                                <Badge
                                  variant="outline"
                                  className="text-xs uppercase bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300 border-purple-200 dark:border-purple-800"
                                  data-testid="method-badge-scraped"
                                >
                                  Web scraped
                                </Badge>
                              ) : (
                                <Badge variant="outline" className="text-xs uppercase">
                                  {item.method || "api"}
                                </Badge>
                              )}
                              {item.fallback_from && (
                                <TooltipProvider>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <span className="inline-flex cursor-help">
                                        <Badge
                                          variant="secondary"
                                          className="text-[10px] bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 hover:bg-amber-100"
                                          data-testid="fallback-badge"
                                        >
                                          via fallback
                                        </Badge>
                                      </span>
                                    </TooltipTrigger>
                                    <TooltipContent>
                                      <p>Failed first: {formatConnectorName(item.fallback_from) || item.fallback_from}</p>
                                    </TooltipContent>
                                  </Tooltip>
                                </TooltipProvider>
                              )}
                            </div>
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

                              {/* Scraping checks chips */}
                              {att.method?.toLowerCase() === "scraping" && (
                                <div className="flex items-center gap-1.5 flex-wrap pt-1" data-testid="attempt-scraping-checks">
                                  <span className="text-[11px] text-muted-foreground font-medium">Checks:</span>
                                  <Badge
                                    variant="outline"
                                    className={`text-[10px] px-1.5 py-0 flex items-center gap-1 ${
                                      att.scraping_checks?.site_policy_allows
                                        ? "border-emerald-500/50 text-emerald-700 dark:text-emerald-400"
                                        : "border-rose-500/50 text-rose-700 dark:text-rose-400"
                                    }`}
                                    data-testid="chip-policy"
                                  >
                                    {att.scraping_checks?.site_policy_allows ? (
                                      <Check className="h-2.5 w-2.5" />
                                    ) : (
                                      <X className="h-2.5 w-2.5" />
                                    )}
                                    policy
                                  </Badge>
                                  <Badge
                                    variant="outline"
                                    className={`text-[10px] px-1.5 py-0 flex items-center gap-1 ${
                                      att.scraping_checks?.other_methods_failed
                                        ? "border-emerald-500/50 text-emerald-700 dark:text-emerald-400"
                                        : "border-rose-500/50 text-rose-700 dark:text-rose-400"
                                    }`}
                                    data-testid="chip-other-methods"
                                  >
                                    {att.scraping_checks?.other_methods_failed ? (
                                      <Check className="h-2.5 w-2.5" />
                                    ) : (
                                      <X className="h-2.5 w-2.5" />
                                    )}
                                    other methods
                                  </Badge>
                                  <Badge
                                    variant="outline"
                                    className={`text-[10px] px-1.5 py-0 flex items-center gap-1 ${
                                      att.scraping_checks?.below_min_threshold
                                        ? "border-emerald-500/50 text-emerald-700 dark:text-emerald-400"
                                        : "border-rose-500/50 text-rose-700 dark:text-rose-400"
                                    }`}
                                    data-testid="chip-threshold"
                                  >
                                    {att.scraping_checks?.below_min_threshold ? (
                                      <Check className="h-2.5 w-2.5" />
                                    ) : (
                                      <X className="h-2.5 w-2.5" />
                                    )}
                                    threshold
                                  </Badge>
                                </div>
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

              {selectedMention.fallback_from && (
                <div className="p-3 rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50/50 dark:bg-amber-950/20 text-xs text-amber-900 dark:text-amber-200 flex items-center justify-between">
                  <span className="font-semibold">Collected via fallback</span>
                  <span>
                    Failed first: <span className="font-mono">{selectedMention.fallback_from}</span>
                  </span>
                </div>
              )}

              {/* Scraped metadata from raw_payload: page_url, license_note, attribution */}
              {(() => {
                const payload = selectedMention.raw_payload || {};
                const pageUrl = payload.page_url || selectedMention.page_url;
                const licenseNote = payload.license_note || selectedMention.license_note;
                const attribution = payload.attribution || selectedMention.attribution;
                const rawHtml = payload.raw_html || selectedMention.raw_html;

                return (
                  <>
                    {(pageUrl || licenseNote || attribution) && (
                      <div className="p-3 rounded-lg border border-border bg-card space-y-2 text-xs" data-testid="scraped-metadata">
                        {pageUrl && (
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-muted-foreground w-24 shrink-0">Page URL:</span>
                            <a
                              href={pageUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="text-primary hover:underline truncate inline-flex items-center gap-1"
                              data-testid="scraped-page-url"
                            >
                              {pageUrl}
                              <ExternalLink className="h-3 w-3 shrink-0" />
                            </a>
                          </div>
                        )}
                        {licenseNote && (
                          <div className="flex items-center gap-2" data-testid="scraped-license-note">
                            <span className="font-semibold text-muted-foreground w-24 shrink-0">Licence note:</span>
                            <span className="text-foreground">{licenseNote}</span>
                          </div>
                        )}
                        {attribution && (
                          <div className="flex items-center gap-2" data-testid="scraped-attribution">
                            <span className="font-semibold text-muted-foreground w-24 shrink-0">Attribution:</span>
                            <span className="text-foreground">{attribution}</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Collapsible Original HTML block (text only, never live HTML) */}
                    {rawHtml && (
                      <div className="p-3 rounded-lg border border-border bg-card space-y-2 text-xs" data-testid="scraped-raw-html-block">
                        <div className="flex items-center justify-between">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => setHtmlExpanded(!htmlExpanded)}
                            className="text-xs h-7 px-2 font-medium"
                            data-testid="toggle-raw-html-btn"
                          >
                            {htmlExpanded ? (
                              <>
                                <ChevronUp className="h-3.5 w-3.5 mr-1" />
                                Hide Original HTML
                              </>
                            ) : (
                              <>
                                <ChevronDown className="h-3.5 w-3.5 mr-1" />
                                Original HTML
                              </>
                            )}
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => handleCopyRawHtml(rawHtml)}
                            className="h-7 text-xs px-2"
                            data-testid="copy-raw-html-btn"
                          >
                            {copiedHtml ? (
                              <>
                                <Check className="h-3 w-3 mr-1 text-emerald-500" />
                                Copied
                              </>
                            ) : (
                              <>
                                <Copy className="h-3 w-3 mr-1" />
                                Copy HTML
                              </>
                            )}
                          </Button>
                        </div>

                        {htmlExpanded && (
                          <pre className="p-3 rounded-md bg-muted/60 text-foreground font-mono text-[11px] overflow-x-auto max-h-64 whitespace-pre-wrap select-text" data-testid="raw-html-content">
                            <code>{rawHtml}</code>
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                );
              })()}

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
