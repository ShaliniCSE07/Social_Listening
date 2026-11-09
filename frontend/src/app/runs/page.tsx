"use client";

import * as React from "react";
import { useEffect, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Layers,
  Search,
  Filter,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  RotateCcw,
  PlusCircle,
  Clock,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import { getRuns, type RunListItem } from "@/lib/api";
import {
  formatCurrency,
  formatNumber,
  formatRelativeTime,
  formatExactDate,
} from "@/lib/utils";
import StatusBadge from "@/components/StatusBadge";
import ErrorBox from "@/components/ErrorBox";
import EmptyState from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";

type SortField = "id" | "status" | "created_at" | "mentions" | "attempts" | "cost";
type SortDirection = "asc" | "desc";

const PAGE_SIZE = 10;

export default function RunsListPage() {
  const router = useRouter();

  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filters & Sorting
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortField, setSortField] = useState<SortField>("created_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [currentPage, setCurrentPage] = useState(1);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getRuns();
      setRuns(data);
    } catch (err: any) {
      setError(err.message || "Failed to load collection runs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
    setCurrentPage(1);
  };

  // Filtered & Sorted runs
  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      // Status filter
      if (statusFilter !== "all") {
        if ((run.status || "").toLowerCase() !== statusFilter.toLowerCase()) {
          return false;
        }
      }

      // Search query filter (matches ID or any company)
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const matchesId = (run.id || "").toLowerCase().includes(q);
        const matchesCompany = (run.companies || []).some((c) =>
          c.toLowerCase().includes(q)
        );
        if (!matchesId && !matchesCompany) return false;
      }

      return true;
    });
  }, [runs, statusFilter, searchQuery]);

  const sortedRuns = useMemo(() => {
    return [...filteredRuns].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "id":
          cmp = (a.id || "").localeCompare(b.id || "");
          break;
        case "status":
          cmp = (a.status || "").localeCompare(b.status || "");
          break;
        case "created_at":
          cmp =
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
        case "mentions":
          cmp =
            (a.totals?.mentions_count || 0) - (b.totals?.mentions_count || 0);
          break;
        case "attempts":
          cmp =
            (a.totals?.attempts_count || 0) - (b.totals?.attempts_count || 0);
          break;
        case "cost":
          cmp = (a.totals?.cost_usd || 0) - (b.totals?.cost_usd || 0);
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
  }, [filteredRuns, sortField, sortDirection]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sortedRuns.length / PAGE_SIZE));
  const paginatedRuns = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return sortedRuns.slice(start, start + PAGE_SIZE);
  }, [sortedRuns, currentPage]);

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) {
      return <ArrowUpDown className="h-3 w-3 ml-1 opacity-40 inline" />;
    }
    return sortDirection === "asc" ? (
      <ArrowUp className="h-3 w-3 ml-1 text-primary inline" />
    ) : (
      <ArrowDown className="h-3 w-3 ml-1 text-primary inline" />
    );
  };

  return (
    <div className="space-y-6" data-testid="runs-list-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">
            Collection Runs
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Search, filter, and inspect your historical pipeline executions.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={loadRuns}
            disabled={loading}
            data-testid="refresh-btn"
          >
            <RotateCcw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button asChild size="sm">
            <Link href="/runs/new">
              <PlusCircle className="h-4 w-4 mr-2" />
              New run
            </Link>
          </Button>
        </div>
      </div>

      {error && <ErrorBox message={error} onRetry={loadRuns} />}

      {/* Main Table Card */}
      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            {/* Search Input */}
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by company or run ID…"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setCurrentPage(1);
                }}
                className="pl-9"
                data-testid="search-input"
              />
            </div>

            {/* Status Filter */}
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground hidden sm:inline" />
              <Select
                value={statusFilter}
                onValueChange={(val) => {
                  setStatusFilter(val);
                  setCurrentPage(1);
                }}
              >
                <SelectTrigger className="w-[140px]" data-testid="status-filter">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="queued">Queued</SelectItem>
                  <SelectItem value="running">Running</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="partial">Partial</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full rounded-md" />
              ))}
            </div>
          ) : sortedRuns.length === 0 ? (
            <div className="p-8">
              <EmptyState
                message={runs.length === 0 ? "No runs yet" : "No matching runs found"}
                description={
                  runs.length === 0
                    ? "Start a new collection run to gather social media mentions."
                    : "Try adjusting your search query or status filter."
                }
                actionHref="/runs/new"
                actionLabel="Start new run"
              />
            </div>
          ) : (
            <TooltipProvider>
              <Table data-testid="runs-table">
                <TableHeader>
                  <TableRow>
                    <TableHead
                      className="cursor-pointer select-none font-semibold text-xs"
                      onClick={() => handleSort("id")}
                    >
                      Run ID {renderSortIcon("id")}
                    </TableHead>
                    <TableHead
                      className="cursor-pointer select-none font-semibold text-xs"
                      onClick={() => handleSort("status")}
                    >
                      Status {renderSortIcon("status")}
                    </TableHead>
                    <TableHead
                      className="cursor-pointer select-none font-semibold text-xs"
                      onClick={() => handleSort("created_at")}
                    >
                      Created {renderSortIcon("created_at")}
                    </TableHead>
                    <TableHead className="font-semibold text-xs">
                      Companies
                    </TableHead>
                    <TableHead
                      className="cursor-pointer select-none font-semibold text-xs text-right"
                      onClick={() => handleSort("mentions")}
                    >
                      Mentions {renderSortIcon("mentions")}
                    </TableHead>
                    <TableHead
                      className="cursor-pointer select-none font-semibold text-xs text-right"
                      onClick={() => handleSort("attempts")}
                    >
                      Attempts {renderSortIcon("attempts")}
                    </TableHead>
                    <TableHead
                      className="cursor-pointer select-none font-semibold text-xs text-right"
                      onClick={() => handleSort("cost")}
                    >
                      Spend {renderSortIcon("cost")}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {paginatedRuns.map((run) => (
                    <TableRow
                      key={run.id}
                      onClick={() => router.push(`/runs/${run.id}`)}
                      className="cursor-pointer hover:bg-muted/60 transition-colors group"
                      data-testid={`run-row-${run.id}`}
                    >
                      <TableCell className="font-mono text-xs font-semibold text-primary">
                        <Link
                          href={`/runs/${run.id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="hover:underline flex items-center gap-1"
                        >
                          {run.id.slice(0, 8)}…
                          <ExternalLink className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                        </Link>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={run.status} />
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span suppressHydrationWarning>
                              {formatRelativeTime(run.created_at)}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent>
                            <span suppressHydrationWarning>
                              {formatExactDate(run.created_at)}
                            </span>
                          </TooltipContent>
                        </Tooltip>
                      </TableCell>
                      <TableCell className="text-sm text-foreground max-w-xs truncate">
                        {run.companies.join(", ") || "—"}
                      </TableCell>
                      <TableCell className="text-right text-sm tabular-nums font-medium text-foreground">
                        {formatNumber(run.totals?.mentions_count)}
                      </TableCell>
                      <TableCell className="text-right text-sm tabular-nums text-muted-foreground">
                        {formatNumber(run.totals?.attempts_count)}
                      </TableCell>
                      <TableCell className="text-right text-sm tabular-nums font-medium text-foreground">
                        {run.totals?.cost_usd > 0
                          ? formatCurrency(run.totals?.cost_usd)
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {/* Pagination Controls */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-6 py-4 border-t border-border">
                  <span className="text-xs text-muted-foreground">
                    Showing {(currentPage - 1) * PAGE_SIZE + 1} to{" "}
                    {Math.min(currentPage * PAGE_SIZE, sortedRuns.length)} of{" "}
                    {sortedRuns.length} runs
                  </span>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                      disabled={currentPage === 1}
                      aria-label="Previous page"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="text-xs font-medium text-foreground px-2">
                      Page {currentPage} of {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                      disabled={currentPage === totalPages}
                      aria-label="Next page"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </TooltipProvider>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
