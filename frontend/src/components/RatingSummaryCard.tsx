"use client";

/**
 * Amazon-style star-rating summary for a run.
 *
 * Shows the average rating and, for each star level (5 → 1), the percentage of
 * rated mentions that gave it. Works for any plugin's output: the backend reads
 * each mention's rating (TripAdvisor, Google Places, datasets with a rating
 * column…); mentions without stars, such as Reddit posts, are reported but not
 * counted in the percentages.
 */
import * as React from "react";
import { useEffect, useState } from "react";
import { Star } from "lucide-react";
import { getRatingSummary, type RatingBreakdown, type RatingSummaryResponse } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface RatingSummaryCardProps {
  runId: string;
  /** Re-fetched when this changes, so the card fills in once a run finishes. */
  runStatus?: string;
  /** Re-fetched when this changes, so the card updates as mentions arrive. */
  mentionsCount?: number;
}

const ALL = "__all__";

export function StarRow({ value, size = "h-4 w-4" }: { value: number; size?: string }) {
  const pct = Math.max(0, Math.min(100, (value / 5) * 100));
  return (
    <span
      className="relative inline-flex"
      role="img"
      aria-label={`${value.toFixed(1)} out of 5 stars`}
      data-testid="star-row"
    >
      <span className="flex text-muted-foreground/30">
        {[0, 1, 2, 3, 4].map((i) => (
          <Star key={i} className={`${size} fill-current`} />
        ))}
      </span>
      <span className="absolute inset-0 flex overflow-hidden text-highlight" style={{ width: `${pct}%` }}>
        {[0, 1, 2, 3, 4].map((i) => (
          <Star key={i} className={`${size} shrink-0 fill-current`} />
        ))}
      </span>
    </span>
  );
}

function Breakdown({ data }: { data: RatingBreakdown }) {
  return (
    <div className="grid gap-6 sm:grid-cols-[minmax(0,180px)_1fr] items-center">
      <div className="space-y-1" data-testid="rating-average">
        <div className="flex items-baseline gap-1.5">
          <span className="text-4xl font-bold tabular-nums">{data.average?.toFixed(1)}</span>
          <span className="text-sm text-muted-foreground">out of 5</span>
        </div>
        <StarRow value={data.average ?? 0} size="h-5 w-5" />
        <p className="text-xs text-muted-foreground">
          {data.rated_count.toLocaleString()} {data.rated_count === 1 ? "rating" : "ratings"}
        </p>
      </div>

      <ul className="space-y-2" data-testid="rating-distribution">
        {data.distribution.map((b) => (
          <li key={b.stars} className="flex items-center gap-3 text-sm" data-testid={`rating-bar-${b.stars}`}>
            <span className="w-12 shrink-0 text-muted-foreground">{b.stars} star</span>
            <div
              className="h-3 flex-1 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label={`${b.stars} star`}
              aria-valuenow={b.percent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="h-full rounded-full bg-highlight transition-all" style={{ width: `${b.percent}%` }} />
            </div>
            <span className="w-12 shrink-0 text-right tabular-nums">{Math.round(b.percent)}%</span>
            <span className="hidden w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground sm:inline">
              ({b.count})
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function RatingSummaryCard({ runId, runStatus, mentionsCount }: RatingSummaryCardProps) {
  const [summary, setSummary] = useState<RatingSummaryResponse | null>(null);
  const [error, setError] = useState("");
  const [platform, setPlatform] = useState<string>(ALL);

  useEffect(() => {
    let cancelled = false;
    getRatingSummary(runId)
      .then((res) => {
        if (!cancelled) {
          setSummary(res);
          setError("");
        }
      })
      .catch((err: any) => {
        if (!cancelled) setError(err?.message || "Could not load the rating summary");
      });
    return () => {
      cancelled = true;
    };
  }, [runId, runStatus, mentionsCount]);

  if (error) {
    return (
      <Card data-testid="rating-summary-card">
        <CardHeader>
          <CardTitle className="text-base">Star rating summary</CardTitle>
          <CardDescription className="text-rose-600 dark:text-rose-400">{error}</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  // Hide until there is a well-formed summary for a run that has mentions.
  if (!summary || !summary.total_mentions || !Array.isArray(summary.distribution)) return null;

  const byPlatform = summary.by_platform ?? {};
  const ratedPlatforms = Object.entries(byPlatform)
    .filter(([, b]) => (b?.rated_count ?? 0) > 0)
    .map(([p]) => p);
  const current: RatingBreakdown = platform !== ALL && byPlatform[platform] ? byPlatform[platform] : summary;

  return (
    <Card data-testid="rating-summary-card">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="text-base flex items-center gap-2">
              <Star className="h-4 w-4 text-highlight fill-current" />
              Star rating summary
            </CardTitle>
            <CardDescription>Share of reviews at each star rating, across every source in this run.</CardDescription>
          </div>
          {ratedPlatforms.length > 1 && (
            <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by platform">
              {[ALL, ...ratedPlatforms].map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPlatform(p)}
                  aria-pressed={platform === p}
                  data-testid={`rating-platform-${p === ALL ? "all" : p}`}
                  className={`rounded-full border px-2.5 py-0.5 text-xs capitalize transition-colors ${
                    platform === p
                      ? "border-highlight bg-highlight/10 text-foreground"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {p === ALL ? "All sources" : p}
                </button>
              ))}
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {current.rated_count > 0 ? (
          <Breakdown data={current} />
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="rating-summary-empty">
            No star ratings in this run yet. Ratings come from review sources such as TripAdvisor, Google
            Places, or datasets with a rating column.
          </p>
        )}
        {current.unrated_count > 0 && current.rated_count > 0 && (
          <p className="text-xs text-muted-foreground" data-testid="rating-unrated-note">
            {current.unrated_count.toLocaleString()} of {current.total_mentions.toLocaleString()} mentions have no
            star rating (for example Reddit posts) and are not counted.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
