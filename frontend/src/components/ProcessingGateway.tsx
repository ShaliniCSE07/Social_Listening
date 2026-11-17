"use client";

/**
 * Collection → processing gateway.
 *
 * Shown on a run's detail page. Once collection has finished, it sends the
 * run's mentions.jsonl / attempts.jsonl to the processing step (Member 2) on
 * the same backend, and links to the data processing dashboard.
 */
import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Loader2,
  RotateCcw,
  Workflow,
} from "lucide-react";
import {
  getProcessingAvailability,
  getProcessingDashboardUrl,
  getRunProcessing,
  startRunProcessing,
  type ProcessingAvailability,
  type RunProcessingState,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const POLL_MS = 3000;
const ACTIVE = new Set(["queued", "running"]);
const KNOWN = new Set(["not_started", "queued", "running", "completed", "failed"]);

interface ProcessingGatewayProps {
  runId: string;
  runStatus: string;
  mentionsCount: number;
}

function normalise(state: RunProcessingState | null): RunProcessingState | null {
  if (!state || typeof state.status !== "string" || !KNOWN.has(state.status)) return null;
  return state;
}

export default function ProcessingGateway({ runId, runStatus, mentionsCount }: ProcessingGatewayProps) {
  const [availability, setAvailability] = useState<ProcessingAvailability | null>(null);
  const [state, setState] = useState<RunProcessingState | null>(null);
  const [starting, setStarting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const collectionRunning = runStatus === "running" || runStatus === "queued";
  const collectionProcessable = runStatus === "completed" || runStatus === "partial";
  const dashboardUrl = getProcessingDashboardUrl();

  const loadState = useCallback(async () => {
    try {
      setState(normalise(await getRunProcessing(runId)));
    } catch {
      // Keep the last known state; the backend may be restarting.
    }
  }, [runId]);

  useEffect(() => {
    if (collectionRunning) return;
    let cancelled = false;
    getProcessingAvailability()
      .then((a) => {
        if (!cancelled) setAvailability(typeof a?.available === "boolean" ? a : null);
      })
      .catch(() => {
        if (!cancelled) setAvailability(null);
      });
    loadState();
    return () => {
      cancelled = true;
    };
  }, [collectionRunning, loadState]);

  const status = state?.status ?? "not_started";
  const isActive = ACTIVE.has(status);

  useEffect(() => {
    if (!isActive) return;
    pollRef.current = setInterval(loadState, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [isActive, loadState]);

  const handleStart = async () => {
    setStarting(true);
    setActionError(null);
    try {
      setState(normalise(await startRunProcessing(runId)) ?? { run_id: runId, status: "queued" });
    } catch (err: any) {
      setActionError(err?.message || "Could not start processing.");
      loadState();
    } finally {
      setStarting(false);
    }
  };

  const unavailable = availability?.available === false;
  const canStart =
    collectionProcessable &&
    mentionsCount > 0 &&
    !unavailable &&
    !isActive &&
    status !== "completed" &&
    !starting;

  let description: string;
  if (collectionRunning) {
    description = "Available once collection finishes.";
  } else if (!collectionProcessable) {
    description = "This collection run did not finish successfully, so there is nothing to process.";
  } else if (mentionsCount === 0) {
    description = "This run collected no mentions, so there is nothing to process.";
  } else if (status === "completed") {
    description = "Processing finished. Explore the cleaned records in the processing dashboard.";
  } else if (isActive) {
    description = "Cleaning, de-duplicating and masking the collected mentions…";
  } else if (status === "failed") {
    description = "Processing failed. Check the error below and try again.";
  } else {
    description = "Send this run's collected mentions to the processing pipeline (cleaning, de-duplication, masking, storage).";
  }

  const counters = state?.counters || {};

  return (
    <Card className="shadow-sm" data-testid="processing-gateway">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          <Workflow className="h-4 w-4 text-primary" />
          Next step: Data processing
        </CardTitle>
        <CardDescription className="text-xs" data-testid="processing-gateway-description">
          {description}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Step indicator */}
        <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
          <span className="flex items-center gap-1.5">
            {collectionRunning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
            )}
            1. Collection
          </span>
          <ArrowRight className="h-3.5 w-3.5" />
          <span className="flex items-center gap-1.5" data-testid="processing-step-status">
            {isActive && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {status === "completed" && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
            {status === "failed" && <AlertTriangle className="h-3.5 w-3.5 text-rose-500" />}
            2. Processing
            {isActive && " (in progress)"}
            {status === "completed" && " (done)"}
            {status === "failed" && " (failed)"}
          </span>
        </div>

        {status === "completed" && (
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs" data-testid="processing-summary">
            {[
              ["Records saved", state?.record_count ?? 0],
              ["Duplicates removed", counters.duplicates ?? 0],
              ["Quarantined", counters.quarantined ?? 0],
              ["Wrong company", counters.wrong_company ?? 0],
            ].map(([label, value]) => (
              <div key={label as string} className="rounded-lg border border-border p-3">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="text-base font-semibold text-foreground tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        )}

        {status === "failed" && state?.error && (
          <p className="text-xs text-rose-700 dark:text-rose-300 break-words" data-testid="processing-error">
            {state.error}
          </p>
        )}

        {actionError && (
          <p className="text-xs text-rose-700 dark:text-rose-300 break-words" data-testid="processing-action-error">
            {actionError}
          </p>
        )}

        {unavailable && !collectionRunning && (
          <p className="text-xs text-amber-700 dark:text-amber-300 flex items-start gap-1.5" data-testid="processing-unavailable">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>Processing is unavailable: {availability?.reason || "unknown reason"}</span>
          </p>
        )}

        <div className="flex items-center gap-2 flex-wrap">
          {status !== "completed" && (
            <Button
              size="sm"
              onClick={handleStart}
              disabled={!canStart}
              className="flex items-center gap-1.5"
              data-testid="start-processing-btn"
            >
              {starting || isActive ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : status === "failed" ? (
                <RotateCcw className="h-3.5 w-3.5" />
              ) : (
                <ArrowRight className="h-3.5 w-3.5" />
              )}
              {isActive ? "Processing…" : status === "failed" ? "Retry processing" : "Send to processing"}
            </Button>
          )}
          <Button
            asChild
            size="sm"
            variant={status === "completed" ? "default" : "outline"}
          >
            <a
              href={dashboardUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5"
              data-testid="open-processing-dashboard"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open processing dashboard
            </a>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
