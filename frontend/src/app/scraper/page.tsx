"use client";

/**
 * Web Scraper: paste any URL, get its reviews as mentions.jsonl.
 * Separate from collection runs; uses the backend's review scraper engine.
 */
import * as React from "react";
import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Download, Globe, Info, Loader2, Search } from "lucide-react";
import {
  getScrapeDownloadUrl,
  getScrapeJob,
  getScrapeJobs,
  getScraperCapabilities,
  scrapeReviews,
  type ScrapeJob,
  type ScrapeMode,
} from "@/lib/api";
import ErrorBox from "@/components/ErrorBox";
import { StarRow } from "@/components/RatingSummaryCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const METHOD_LABELS: Record<string, string> = {
  json_ld: "structured data (JSON-LD)",
  microdata: "structured data (microdata)",
  heuristic: "page layout detection",
  repeated_blocks: "repeated review blocks",
};

const MODE_OPTIONS: { value: ScrapeMode; label: string; help: string }[] = [
  { value: "auto", label: "Auto", help: "Reads the page HTML first; opens it in a browser only if no reviews are found." },
  { value: "static", label: "Fast (HTML only)", help: "Quickest. Misses reviews that are loaded by JavaScript." },
  { value: "browser", label: "Browser (JavaScript)", help: "Opens the page in a headless browser so JavaScript-loaded reviews appear. Slower (about 10–20 s per page)." },
];

function statusBadge(status: string) {
  if (status === "completed") return <Badge className="bg-emerald-600 hover:bg-emerald-600">completed</Badge>;
  if (status === "empty") return <Badge variant="secondary">no reviews</Badge>;
  return <Badge variant="destructive">failed</Badge>;
}

export default function ScraperPage() {
  const [url, setUrl] = useState("");
  const [company, setCompany] = useState("");
  const [maxPages, setMaxPages] = useState("3");
  const [maxReviews, setMaxReviews] = useState("200");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState<ScrapeJob | null>(null);
  const [history, setHistory] = useState<ScrapeJob[]>([]);
  const [mode, setMode] = useState<ScrapeMode>("auto");
  const [browserOk, setBrowserOk] = useState<boolean | null>(null);
  const [browserReason, setBrowserReason] = useState("");

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await getScrapeJobs());
    } catch {
      // history is optional
    }
  }, []);

  useEffect(() => {
    loadHistory();
    getScraperCapabilities()
      .then((c) => {
        setBrowserOk(c.browser_available);
        setBrowserReason(c.browser_reason);
      })
      .catch(() => setBrowserOk(null));
  }, [loadHistory]);

  const urlValid = /^https?:\/\/\S+\.\S+/i.test(url.trim());

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!urlValid || running) return;
    setRunning(true);
    setError("");
    setJob(null);
    try {
      const res = await scrapeReviews({
        url: url.trim(),
        company: company.trim() || undefined,
        max_pages: Math.min(10, Math.max(1, parseInt(maxPages, 10) || 3)),
        max_reviews: Math.min(1000, Math.max(1, parseInt(maxReviews, 10) || 200)),
        mode,
      });
      setJob(res);
      loadHistory();
    } catch (err: any) {
      setError(err?.message || "Scraping failed");
    } finally {
      setRunning(false);
    }
  };

  const openJob = async (id: string) => {
    setError("");
    try {
      setJob(await getScrapeJob(id));
    } catch (err: any) {
      setError(err?.message || "Could not load that scrape");
    }
  };

  const rated = (job?.reviews ?? []).filter((r) => typeof r.rating === "number") as { rating: number }[];
  const avg = rated.length ? rated.reduce((s, r) => s + r.rating, 0) / rated.length : null;

  return (
    <div className="space-y-6" data-testid="scraper-page">
      <div>
        <h2 className="page-title">Web Scraper</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Paste a link to any page with reviews. The reviews are extracted and saved as a{" "}
          <code className="text-xs">mentions.jsonl</code> file in the same format as collection runs.
        </p>
      </div>

      <Card>
        <CardContent className="p-6">
          <form onSubmit={onSubmit} className="space-y-4" data-testid="scraper-form">
            <div className="space-y-1.5">
              <label htmlFor="scrape-url" className="text-sm font-medium">Page URL</label>
              <Input
                id="scrape-url"
                type="url"
                inputMode="url"
                placeholder="https://example.com/product/reviews"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                data-testid="scrape-url"
                required
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5">
                <label htmlFor="scrape-company" className="text-sm font-medium">Company / product (optional)</label>
                <Input
                  id="scrape-company"
                  placeholder="Detected from the page if empty"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  maxLength={200}
                  data-testid="scrape-company"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="scrape-pages" className="text-sm font-medium">Max pages (1–10)</label>
                <Input id="scrape-pages" type="number" min={1} max={10} value={maxPages}
                  onChange={(e) => setMaxPages(e.target.value)} data-testid="scrape-pages" />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="scrape-max" className="text-sm font-medium">Max reviews (1–1000)</label>
                <Input id="scrape-max" type="number" min={1} max={1000} value={maxReviews}
                  onChange={(e) => setMaxReviews(e.target.value)} data-testid="scrape-max" />
              </div>
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">Scraping mode</span>
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Scraping mode">
                {MODE_OPTIONS.map((o) => {
                  const disabled = o.value === "browser" && browserOk === false;
                  return (
                    <button
                      key={o.value}
                      type="button"
                      role="radio"
                      aria-checked={mode === o.value}
                      disabled={disabled}
                      onClick={() => setMode(o.value)}
                      data-testid={`scrape-mode-${o.value}`}
                      className={`rounded-full border px-3 py-1 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                        mode === o.value
                          ? "border-primary bg-primary/10 text-foreground font-medium"
                          : "border-border text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {o.label}
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-muted-foreground" data-testid="scrape-mode-help">
                {MODE_OPTIONS.find((o) => o.value === mode)?.help}
              </p>
              {browserOk === false && (
                <p className="text-xs text-amber-700 dark:text-amber-400" data-testid="scrape-browser-missing">
                  Browser mode is not installed on the server. {browserReason}
                </p>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={!urlValid || running} data-testid="scrape-submit">
                {running ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Search className="h-4 w-4 mr-2" />}
                {running ? "Scraping…" : "Scrape reviews"}
              </Button>
              {running && (
                <span className="text-xs text-muted-foreground">
                  {mode === "browser"
                    ? "Opening pages in a headless browser and waiting for reviews to load. This can take a minute or two."
                    : "Fetching pages politely (about 1 second between pages). This can take up to a minute."}
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground flex items-start gap-1.5">
              <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              Browser mode handles reviews loaded by JavaScript. Sites that block bots (e.g. Amazon, TripAdvisor) or
              whose robots.txt disallows bots (e.g. Trustpilot, IMDb) still return no reviews. robots.txt is respected.
            </p>
          </form>
        </CardContent>
      </Card>

      {error && <ErrorBox message={error} />}

      {job && (
        <Card data-testid="scrape-result">
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1 min-w-0">
                <CardTitle className="text-base flex items-center gap-2">
                  {job.status === "completed" ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <AlertCircle className="h-4 w-4 text-amber-600" />
                  )}
                  {job.company || "Scrape result"} {statusBadge(job.status)}
                </CardTitle>
                <CardDescription className="break-all">{job.url}</CardDescription>
              </div>
              {job.status !== "failed" && (
                <Button asChild variant="outline" data-testid="scrape-download">
                  <a href={getScrapeDownloadUrl(job)} download>
                    <Download className="h-4 w-4 mr-2" /> Download mentions.jsonl
                  </a>
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm" data-testid="scrape-stats">
              <span><strong>{job.reviews_count}</strong> reviews</span>
              <span><strong>{job.pages_fetched}</strong> page{job.pages_fetched === 1 ? "" : "s"} fetched</span>
              {job.mode_used && (
                <span data-testid="scrape-mode-used">
                  {job.mode_used === "browser" ? "rendered in browser (JavaScript)" : "read from page HTML"}
                </span>
              )}
              {avg !== null && (
                <span className="inline-flex items-center gap-2" data-testid="scrape-average">
                  <StarRow value={avg} /> {avg.toFixed(1)} average from {rated.length} rated
                </span>
              )}
              {Object.entries(job.methods || {}).map(([m, n]) => (
                <span key={m} className="text-muted-foreground">
                  {n} via {METHOD_LABELS[m] ?? m}
                </span>
              ))}
            </div>

            {job.error && (
              <p className="text-sm text-rose-600 dark:text-rose-400" data-testid="scrape-error">{job.error}</p>
            )}
            {job.warnings?.map((w, i) => (
              <p key={i} className="text-xs text-amber-700 dark:text-amber-400 flex items-start gap-1.5" data-testid="scrape-warning">
                <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" /> {w}
              </p>
            ))}

            {(job.reviews?.length ?? 0) > 0 && (
              <ul className="divide-y divide-border rounded-lg border border-border" data-testid="scrape-reviews">
                {job.reviews!.map((r, i) => (
                  <li key={i} className="p-3 space-y-1">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      {typeof r.rating === "number" && (
                        <span className="inline-flex items-center gap-1">
                          <StarRow value={r.rating} size="h-3.5 w-3.5" /> {r.rating.toFixed(1)}
                        </span>
                      )}
                      {typeof r.recommended === "boolean" && (
                        <span
                          className={r.recommended ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}
                          data-testid="scrape-recommended"
                        >
                          {r.recommended ? "Recommended" : "Not recommended"}
                        </span>
                      )}
                      {r.author && <span className="font-medium text-foreground">{r.author}</span>}
                      {r.date && <span>{r.date}</span>}
                    </div>
                    {r.title && <p className="text-sm font-medium">{r.title}</p>}
                    <p className="text-sm text-foreground/90 whitespace-pre-line break-words">{r.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      {history.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2"><Globe className="h-4 w-4" /> Recent scrapes</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border" data-testid="scrape-history">
              {history.map((h) => (
                <li key={h.job_id} className="py-2 flex flex-wrap items-center justify-between gap-2 text-sm">
                  <button
                    type="button"
                    onClick={() => openJob(h.job_id)}
                    className="text-left min-w-0 flex-1 hover:underline"
                  >
                    <span className="font-medium">{h.company || h.url}</span>
                    <span className="block text-xs text-muted-foreground truncate">{h.url}</span>
                  </button>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    {h.reviews_count} reviews {statusBadge(h.status)}
                    <span>{new Date(h.created_at).toLocaleString()}</span>
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
