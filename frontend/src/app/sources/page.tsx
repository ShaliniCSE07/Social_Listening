"use client";

import * as React from "react";
import { useEffect, useState, useCallback } from "react";
import {
  Radio,
  Database,
  Globe,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  FileText,
  KeyRound,
  Layers,
} from "lucide-react";
import {
  getSources,
  getDatasets,
  getScrapingSites,
  type SourceConfigItem,
  type DatasetConfigItem,
  type ScrapingSiteConfigItem,
} from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import ErrorBox from "@/components/ErrorBox";
import LoadingState from "@/components/LoadingState";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceConfigItem[]>([]);
  const [datasets, setDatasets] = useState<DatasetConfigItem[]>([]);
  const [scrapingSites, setScrapingSites] = useState<ScrapingSiteConfigItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [src, ds, sites] = await Promise.all([getSources(), getDatasets(), getScrapingSites()]);
      setSources(src);
      setDatasets(ds);
      setScrapingSites(sites);
    } catch (err: any) {
      setError(err.message || "Failed to load sources and dataset configurations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const apiSources = sources.filter((s) => s.method === "api");
  const scrapingSource = sources.find((s) => s.method === "scraping");
  const scrapingReady = !!(scrapingSource?.enabled && scrapingSource?.can_run);

  return (
    <div className="space-y-6" data-testid="sources-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">
            Source Integrations
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Review live API connectors, required credentials, and available offline dataset catalogues.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={loadData}
          disabled={loading}
          data-testid="refresh-sources-btn"
        >
          <RotateCcw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {error && <ErrorBox message={error} onRetry={loadData} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* API Method Card */}
        <Card className="shadow-sm">
          <CardHeader>
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Radio className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-lg">Live API Connectors</CardTitle>
                <CardDescription>
                  Direct query integrations with third-party social APIs.
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <div className="space-y-3">
                {[1, 2].map((i) => (
                  <Skeleton key={i} className="h-20 w-full rounded-xl" />
                ))}
              </div>
            ) : apiSources.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                No API connectors registered.
              </p>
            ) : (
              <div className="space-y-3">
                {apiSources.map((s) => {
                  const isReady = s.enabled && s.can_run;
                  return (
                    <div
                      key={s.name}
                      className="p-4 rounded-xl border border-border bg-card/60 space-y-2"
                      data-testid={`source-item-${s.name}`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-sm text-foreground capitalize">
                            {s.name.replace("_", " ")}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            ({s.platforms.join(", ")})
                          </span>
                        </div>
                        {isReady ? (
                          <Badge variant="success" className="text-xs">
                            Ready
                          </Badge>
                        ) : (
                          <Badge variant="warning" className="text-xs">
                            Needs setup
                          </Badge>
                        )}
                      </div>

                      <div className="text-xs text-muted-foreground">
                        {isReady ? (
                          <span className="text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            Credentials configured and active
                          </span>
                        ) : (
                          <span className="text-amber-600 dark:text-amber-400 flex items-center gap-1">
                            <AlertCircle className="h-3.5 w-3.5" />
                            {s.reason || "Missing credentials in environment"}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Dataset Catalogue Card */}
        <Card className="shadow-sm">
          <CardHeader>
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Database className="h-4 w-4" />
              </div>
              <div>
                <CardTitle className="text-lg">Dataset Catalogue</CardTitle>
                <CardDescription>
                  Offline reviews and historical tweet records across storage formats.
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-20 w-full rounded-xl" />
                ))}
              </div>
            ) : datasets.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                No dataset catalogue entries registered.
              </p>
            ) : (
              <div className="space-y-3">
                {datasets.map((d) => (
                  <div
                    key={d.key}
                    className="p-4 rounded-xl border border-border bg-card/60 space-y-1.5"
                    data-testid={`dataset-item-${d.key}`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-sm text-foreground">
                        {d.name}
                      </span>
                      <Badge variant="secondary" className="text-xs uppercase">
                        {d.source_type}
                      </Badge>
                    </div>

                    <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                      <span className="font-mono">{d.key}</span>
                      {d.last_updated && (
                        <span>Updated: {d.last_updated}</span>
                      )}
                      {d.license_note && (
                        <span>Licence: {d.license_note}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Web Scraping Card — full width below the grid */}
      <Card className="shadow-sm" data-testid="scraping-card">
        <CardHeader>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Globe className="h-4 w-4" />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-3">
                <CardTitle className="text-lg">Web Scraping</CardTitle>
                {scrapingSource && (
                  scrapingReady ? (
                    <Badge variant="success" className="text-xs">Ready</Badge>
                  ) : (
                    <Badge variant="warning" className="text-xs">Needs setup</Badge>
                  )
                )}
              </div>
              <CardDescription>
                Fallback scraping via public site policies. Governed by a safety gate (robots.txt + contact header).
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full rounded-xl" />
            </div>
          ) : !scrapingSource ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              No scraping connector registered.
            </p>
          ) : (
            <div className="space-y-3">
              {/* Overall connector status */}
              <div className="text-xs text-muted-foreground mb-2">
                {scrapingReady ? (
                  <span className="text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Safety gate passed — scraping active
                  </span>
                ) : (
                  <span className="text-amber-600 dark:text-amber-400 flex items-center gap-1">
                    <AlertCircle className="h-3.5 w-3.5" />
                    {scrapingSource.reason || "Scraping not configured"}
                  </span>
                )}
              </div>

              {/* Per-site rows */}
              {scrapingSites.length === 0 ? (
                <p className="text-sm text-muted-foreground">No scraping sites configured.</p>
              ) : (
                scrapingSites.map((site) => (
                  <div
                    key={site.key}
                    className="p-4 rounded-xl border border-border bg-card/60 space-y-1.5"
                    data-testid={`scraping-site-${site.key}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-foreground">{site.name}</span>
                        <span className="text-xs text-muted-foreground capitalize">({site.platform})</span>
                      </div>
                      {site.can_run ? (
                        <Badge variant="success" className="text-xs">Ready</Badge>
                      ) : (
                        <Badge variant="warning" className="text-xs">Needs setup</Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                      <span className="font-mono">{site.key}</span>
                      {site.allows_scraping ? (
                        <span className="text-emerald-600 dark:text-emerald-400">Scraping allowed</span>
                      ) : (
                        <span className="text-red-500">Scraping not allowed</span>
                      )}
                      {site.license_note && <span>Licence: {site.license_note}</span>}
                      {site.attribution && <span>Credit: {site.attribution}</span>}
                      {!site.can_run && site.reason && (
                        <span className="text-amber-600 dark:text-amber-400">↳ {site.reason}</span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

