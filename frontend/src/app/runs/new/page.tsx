"use client";

import * as React from "react";
import { useEffect, useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Building2,
  Database,
  Radio,
  Sliders,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Plus,
  Trash2,
  ChevronDown,
  ChevronUp,
  FileText,
  AlertCircle,
  Sparkles,
  Layers,
  Calendar,
  DollarSign,
  RefreshCw,
  Clock,
  ShieldAlert,
} from "lucide-react";
import {
  getSources,
  getDatasets,
  createRun,
  ApiError,
  type SourceConfigItem,
  type DatasetConfigItem,
  type CompanyInput,
  type CreateRunRequest,
} from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import ErrorBox from "@/components/ErrorBox";
import LoadingState from "@/components/LoadingState";
import { toast } from "sonner";

interface CompanyFormItem {
  id: string;
  name: string;
  industry: string;
  alt_spellings: string;
  handles: string;
  branches: string;
  showDetails: boolean;
}

const STEP_TITLES = [
  { step: 1, title: "Companies", icon: Building2 },
  { step: 2, title: "Sources", icon: Database },
  { step: 3, title: "Options", icon: Sliders },
  { step: 4, title: "Review", icon: CheckCircle2 },
];

export default function NewRunWizardPage() {
  const router = useRouter();

  // Wizard Step
  const [currentStep, setCurrentStep] = useState(1);

  // Config data
  const [sources, setSources] = useState<SourceConfigItem[]>([]);
  const [datasets, setDatasets] = useState<DatasetConfigItem[]>([]);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [configError, setConfigError] = useState("");

  // Step 1: Companies
  const [companies, setCompanies] = useState<CompanyFormItem[]>([
    {
      id: "comp_1",
      name: "",
      industry: "",
      alt_spellings: "",
      handles: "",
      branches: "",
      showDetails: false,
    },
  ]);
  const [bulkPasteText, setBulkPasteText] = useState("");
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);

  // Step 2: Sources
  const [selectedPlatforms, setSelectedPlatforms] = useState<Set<string>>(new Set());
  const [selectedDatasets, setSelectedDatasets] = useState<Set<string>>(new Set());

  // Step 3: Options
  const [budgetUsd, setBudgetUsd] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [maxAgeDays, setMaxAgeDays] = useState("");
  const [requireFresh, setRequireFresh] = useState(false);
  const [refresh, setRefresh] = useState(false);

  // Submit status
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const loadConfig = useCallback(async () => {
    setLoadingConfig(true);
    setConfigError("");
    try {
      const [src, data] = await Promise.all([getSources(), getDatasets()]);
      setSources(src);
      setDatasets(data);
    } catch (err: any) {
      setConfigError(err.message || "Failed to load configuration");
    } finally {
      setLoadingConfig(false);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  // Split comma-separated helper
  const splitList = (val: string): string[] =>
    val
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

  // Company management
  const addCompany = () => {
    setCompanies((prev) => [
      ...prev,
      {
        id: `comp_${Date.now()}_${Math.random()}`,
        name: "",
        industry: "",
        alt_spellings: "",
        handles: "",
        branches: "",
        showDetails: false,
      },
    ]);
  };

  const removeCompany = (id: string) => {
    setCompanies((prev) => (prev.length <= 1 ? prev : prev.filter((c) => c.id !== id)));
  };

  const updateCompany = (id: string, field: keyof CompanyFormItem, value: any) => {
    setCompanies((prev) =>
      prev.map((c) => (c.id === id ? { ...c, [field]: value } : c))
    );
  };

  const handleBulkPaste = () => {
    const lines = bulkPasteText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (lines.length === 0) return;

    const newItems: CompanyFormItem[] = lines.map((line, idx) => ({
      id: `bulk_${Date.now()}_${idx}`,
      name: line,
      industry: "",
      alt_spellings: "",
      handles: "",
      branches: "",
      showDetails: false,
    }));

    // Replace if first entry is blank, otherwise append
    setCompanies((prev) => {
      const firstIsBlank = prev.length === 1 && !prev[0].name.trim();
      return firstIsBlank ? newItems : [...prev, ...newItems];
    });

    setBulkPasteText("");
    setBulkDialogOpen(false);
    toast.success(`Added ${lines.length} companies from list`);
  };

  // Source selection helpers
  const togglePlatform = (plat: string) => {
    setSelectedPlatforms((prev) => {
      const next = new Set(prev);
      next.has(plat) ? next.delete(plat) : next.add(plat);
      return next;
    });
  };

  const toggleDataset = (key: string) => {
    setSelectedDatasets((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  // Group datasets by source_type
  const datasetGroups = useMemo(() => {
    const groups: Record<string, DatasetConfigItem[]> = {
      local: [],
      url: [],
      kaggle: [],
    };
    datasets.forEach((d) => {
      const type = (d.source_type || "local").toLowerCase();
      if (!groups[type]) groups[type] = [];
      groups[type].push(d);
    });
    return groups;
  }, [datasets]);

  const selectAllDatasetsInTab = (sourceType: string) => {
    const items = datasetGroups[sourceType] || [];
    const enabledKeys = items.filter((d) => d.enabled).map((d) => d.key);
    const allSelected = enabledKeys.every((k) => selectedDatasets.has(k));

    setSelectedDatasets((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        enabledKeys.forEach((k) => next.delete(k));
      } else {
        enabledKeys.forEach((k) => next.add(k));
      }
      return next;
    });
  };

  // Step Validation
  const isStep1Valid = useMemo(() => {
    return companies.some((c) => c.name.trim().length > 0);
  }, [companies]);

  const isStep2Valid = useMemo(() => {
    return selectedPlatforms.size > 0 || selectedDatasets.size > 0;
  }, [selectedPlatforms, selectedDatasets]);

  const isStep3Valid = true; // Options are optional

  const canGoNext = useMemo(() => {
    if (currentStep === 1) return isStep1Valid;
    if (currentStep === 2) return isStep2Valid;
    if (currentStep === 3) return isStep3Valid;
    return true;
  }, [currentStep, isStep1Valid, isStep2Valid, isStep3Valid]);

  // Submission
  const handleStartRun = async () => {
    setSubmitting(true);
    setSubmitError("");

    const validCompanies: CompanyInput[] = companies
      .filter((c) => c.name.trim())
      .map((c) => {
        const item: CompanyInput = { name: c.name.trim() };
        const alt = splitList(c.alt_spellings);
        if (alt.length) item.alt_spellings = alt;
        const hnd = splitList(c.handles);
        if (hnd.length) item.handles = hnd;
        const br = splitList(c.branches);
        if (br.length) item.branches = br;
        if (c.industry.trim()) item.industry = c.industry.trim();
        return item;
      });

    const payload: CreateRunRequest = {
      companies: validCompanies,
    };

    const apiPlats = Array.from(selectedPlatforms);
    const dsKeys = Array.from(selectedDatasets);
    if (apiPlats.length || dsKeys.length) {
      payload.sources = {};
      if (apiPlats.length) payload.sources.api = apiPlats;
      if (dsKeys.length) payload.sources.dataset_keys = dsKeys;
    }

    if (budgetUsd) payload.budget_usd = parseFloat(budgetUsd);
    if (dateFrom) payload.date_from = dateFrom;
    if (dateTo) payload.date_to = dateTo;
    if (maxAgeDays) payload.max_age_days = parseFloat(maxAgeDays);
    if (requireFresh) payload.require_fresh = true;
    if (refresh) payload.refresh = true;

    try {
      const res = await createRun(payload);
      toast.success("Run started successfully", {
        description: `Run ID: ${res.run_id}`,
      });
      router.push(`/runs/${res.run_id}`);
    } catch (err: any) {
      if (err instanceof ApiError) {
        setSubmitError(err.message);
      } else {
        setSubmitError("Failed to initiate run. Please try again.");
      }
      toast.error("Failed to start run");
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingConfig) return <LoadingState message="Loading wizard configuration…" />;
  if (configError) return <ErrorBox message={configError} onRetry={loadConfig} />;

  const apiSources = sources.filter((s) => s.method === "api");
  const progressPercent = (currentStep / 4) * 100;

  return (
    <div className="space-y-8" data-testid="new-run-wizard">
      {/* ── Header ── */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-foreground">
          New Collection Run
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          Configure target companies, platforms, dataset catalogs, and run options.
        </p>
      </div>

      {/* ── Stepper ── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          {STEP_TITLES.map((st) => {
            const Icon = st.icon;
            const isCompleted = currentStep > st.step;
            const isCurrent = currentStep === st.step;

            return (
              <div
                key={st.step}
                className="flex items-center gap-2 cursor-pointer"
                onClick={() => {
                  if (st.step < currentStep || (st.step === 2 && isStep1Valid) || (st.step === 3 && isStep1Valid && isStep2Valid)) {
                    setCurrentStep(st.step);
                  }
                }}
              >
                <div
                  className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold transition-colors ${
                    isCurrent
                      ? "bg-primary text-primary-foreground shadow-sm ring-2 ring-primary/30"
                      : isCompleted
                      ? "bg-emerald-500 text-white"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {isCompleted ? <CheckCircle2 className="h-4 w-4" /> : st.step}
                </div>
                <span
                  className={`text-sm font-medium hidden sm:inline ${
                    isCurrent
                      ? "text-foreground font-semibold"
                      : "text-muted-foreground"
                  }`}
                >
                  {st.title}
                </span>
              </div>
            );
          })}
        </div>
        <Progress value={progressPercent} className="h-1.5" />
      </div>

      {submitError && <ErrorBox message={submitError} />}

      {/* ── Two Column Layout (Form + Sticky Summary) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
        {/* Form Body (2 cols) */}
        <div className="lg:col-span-2 space-y-6">
          {/* STEP 1: COMPANIES */}
          {currentStep === 1 && (
            <Card data-testid="step-companies">
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle>Target Companies</CardTitle>
                  <CardDescription>
                    Add companies, alternate spellings, handles, and industry keywords.
                  </CardDescription>
                </div>
                <Dialog open={bulkDialogOpen} onOpenChange={setBulkDialogOpen}>
                  <DialogTrigger asChild>
                    <Button variant="outline" size="sm">
                      <FileText className="h-4 w-4 mr-2" />
                      Paste list
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>Paste Company Names</DialogTitle>
                      <DialogDescription>
                        Paste multiple company names, one per line.
                      </DialogDescription>
                    </DialogHeader>
                    <textarea
                      value={bulkPasteText}
                      onChange={(e) => setBulkPasteText(e.target.value)}
                      placeholder="Acme Corp&#10;Globex International&#10;Initech"
                      rows={6}
                      className="w-full rounded-lg border border-input bg-background p-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <DialogFooter>
                      <Button
                        variant="outline"
                        onClick={() => setBulkDialogOpen(false)}
                      >
                        Cancel
                      </Button>
                      <Button onClick={handleBulkPaste}>Add Companies</Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </CardHeader>
              <CardContent className="space-y-4">
                {companies.map((c, index) => (
                  <div
                    key={c.id}
                    className="p-4 rounded-xl border border-border bg-card shadow-sm space-y-3"
                    data-testid={`company-row-${index}`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                        Company #{index + 1}
                      </span>
                      {companies.length > 1 && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => removeCompany(c.id)}
                          className="h-7 w-7 text-destructive hover:bg-destructive/10"
                          aria-label={`Remove company ${index + 1}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs font-medium text-foreground block mb-1">
                          Company Name <span className="text-destructive">*</span>
                        </label>
                        <Input
                          placeholder="e.g. Acme Corp"
                          value={c.name}
                          onChange={(e) => updateCompany(c.id, "name", e.target.value)}
                          data-testid={`company-name-${index}`}
                          required
                        />
                      </div>
                      <div>
                        <label className="text-xs font-medium text-foreground block mb-1">
                          Industry
                        </label>
                        <Input
                          placeholder="e.g. Technology, Retail"
                          value={c.industry}
                          onChange={(e) => updateCompany(c.id, "industry", e.target.value)}
                        />
                      </div>
                    </div>

                    {/* Collapsible Details */}
                    <div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => updateCompany(c.id, "showDetails", !c.showDetails)}
                        className="text-xs text-muted-foreground hover:text-foreground h-7 px-2"
                      >
                        {c.showDetails ? (
                          <>
                            <ChevronUp className="h-3.5 w-3.5 mr-1" />
                            Hide more details
                          </>
                        ) : (
                          <>
                            <ChevronDown className="h-3.5 w-3.5 mr-1" />
                            More details (handles, alt spellings, branches)
                          </>
                        )}
                      </Button>

                      {c.showDetails && (
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3 border-t border-border mt-2">
                          <div>
                            <label className="text-xs font-medium text-muted-foreground block mb-1">
                              Alt spellings (comma-separated)
                            </label>
                            <Input
                              placeholder="Acme, AcmeCorp"
                              value={c.alt_spellings}
                              onChange={(e) => updateCompany(c.id, "alt_spellings", e.target.value)}
                            />
                          </div>
                          <div>
                            <label className="text-xs font-medium text-muted-foreground block mb-1">
                              Handles (comma-separated)
                            </label>
                            <Input
                              placeholder="@acme, @acmecorp"
                              value={c.handles}
                              onChange={(e) => updateCompany(c.id, "handles", e.target.value)}
                            />
                          </div>
                          <div>
                            <label className="text-xs font-medium text-muted-foreground block mb-1">
                              Branches (comma-separated)
                            </label>
                            <Input
                              placeholder="NY, London, Tokyo"
                              value={c.branches}
                              onChange={(e) => updateCompany(c.id, "branches", e.target.value)}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addCompany}
                  className="w-full border-dashed"
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Add another company
                </Button>

                {!isStep1Valid && (
                  <p className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
                    <AlertCircle className="h-3.5 w-3.5" />
                    Please specify at least one valid company name.
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* STEP 2: SOURCES */}
          {currentStep === 2 && (
            <div className="space-y-6" data-testid="step-sources">
              {/* API Platforms */}
              <Card>
                <CardHeader>
                  <CardTitle>API Platforms</CardTitle>
                  <CardDescription>
                    Direct live platform connectors. Credentials must be active to enable collection.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {apiSources.map((s) => {
                      const platform = s.platforms[0] || s.name;
                      const isSelected = selectedPlatforms.has(platform);
                      const isEnabled = s.enabled && s.can_run;

                      return (
                        <div
                          key={s.name}
                          onClick={() => isEnabled && togglePlatform(platform)}
                          className={`flex items-start gap-3 p-4 rounded-xl border transition-all cursor-pointer ${
                            !isEnabled
                              ? "opacity-60 bg-muted/40 border-border cursor-not-allowed"
                              : isSelected
                              ? "border-primary bg-primary/5 ring-1 ring-primary shadow-sm"
                              : "border-border bg-card hover:border-border/80 hover:bg-muted/30"
                          }`}
                          data-testid={`platform-card-${platform}`}
                        >
                          <Checkbox
                            checked={isSelected}
                            disabled={!isEnabled}
                            onClick={(e) => e.stopPropagation()}
                            onCheckedChange={() => isEnabled && togglePlatform(platform)}
                            className="mt-0.5"
                            data-testid={`platform-${platform}`}
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-sm font-semibold text-foreground capitalize">
                                {s.name.replace("_", " ")}
                              </span>
                              {isEnabled ? (
                                <Badge variant="success" className="text-xs">
                                  Ready
                                </Badge>
                              ) : (
                                <Badge variant="warning" className="text-xs">
                                  Needs setup
                                </Badge>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground mt-0.5">
                              Platform: {s.platforms.join(", ")}
                            </p>
                            {!isEnabled && s.reason && (
                              <p
                                className="text-xs text-amber-600 dark:text-amber-400 mt-2 italic"
                                data-testid={`reason-${platform}`}
                              >
                                {s.reason}
                              </p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>

              {/* Datasets */}
              <Card>
                <CardHeader>
                  <CardTitle>Dataset Catalogue</CardTitle>
                  <CardDescription>
                    Historical offline review and tweet datasets from local files, URLs, or Kaggle.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Tabs defaultValue="local" className="w-full">
                    <TabsList className="grid w-full grid-cols-3 mb-4">
                      <TabsTrigger value="local">Local Files</TabsTrigger>
                      <TabsTrigger value="url">Public URL</TabsTrigger>
                      <TabsTrigger value="kaggle">Kaggle</TabsTrigger>
                    </TabsList>

                    {(["local", "url", "kaggle"] as const).map((tabKey) => {
                      const items = datasetGroups[tabKey] || [];
                      const enabledItems = items.filter((d) => d.enabled);

                      return (
                        <TabsContent key={tabKey} value={tabKey} className="space-y-4">
                          <div className="flex items-center justify-between">
                            <span className="text-xs text-muted-foreground">
                              {items.length} dataset{items.length !== 1 ? "s" : ""} available
                            </span>
                            {enabledItems.length > 0 && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => selectAllDatasetsInTab(tabKey)}
                                className="text-xs h-7"
                              >
                                Select / Deselect all
                              </Button>
                            )}
                          </div>

                          {items.length === 0 ? (
                            <p className="text-sm text-muted-foreground text-center py-8">
                              No datasets configured for this source type.
                            </p>
                          ) : (
                            <div className="grid grid-cols-1 gap-3">
                              {items.map((d) => {
                                const isSelected = selectedDatasets.has(d.key);
                                return (
                                  <div
                                    key={d.key}
                                    onClick={() => d.enabled && toggleDataset(d.key)}
                                    className={`flex items-start gap-3 p-3.5 rounded-xl border transition-all ${
                                      !d.enabled
                                        ? "opacity-50 bg-muted/40 border-border cursor-not-allowed"
                                        : isSelected
                                        ? "border-primary bg-primary/5 ring-1 ring-primary shadow-sm cursor-pointer"
                                        : "border-border bg-card hover:bg-muted/30 cursor-pointer"
                                    }`}
                                  >
                                    <Checkbox
                                      checked={isSelected}
                                      disabled={!d.enabled}
                                      onClick={(e) => e.stopPropagation()}
                                      onCheckedChange={() => d.enabled && toggleDataset(d.key)}
                                      className="mt-0.5"
                                      data-testid={`dataset-${d.key}`}
                                    />
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-sm font-medium text-foreground">
                                          {d.name}
                                        </span>
                                        <span className="font-mono text-xs text-muted-foreground">
                                          {d.key}
                                        </span>
                                      </div>
                                      <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground flex-wrap">
                                        {d.last_updated && (
                                          <span>Updated: {d.last_updated}</span>
                                        )}
                                        {d.license_note && (
                                          <span>Licence: {d.license_note}</span>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </TabsContent>
                      );
                    })}
                  </Tabs>

                  {!isStep2Valid && (
                    <p className="text-xs text-amber-600 dark:text-amber-400 mt-4 flex items-center gap-1.5">
                      <AlertCircle className="h-3.5 w-3.5" />
                      Please select at least one API platform or dataset connector.
                    </p>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {/* STEP 3: OPTIONS */}
          {currentStep === 3 && (
            <Card data-testid="step-options">
              <CardHeader>
                <CardTitle>Run Options & Parameters</CardTitle>
                <CardDescription>
                  Configure budget limits, date windows, and dataset caching rules.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Budget */}
                <div className="p-4 rounded-xl border border-border bg-card space-y-2">
                  <div className="flex items-center gap-2">
                    <DollarSign className="h-4 w-4 text-primary" />
                    <label className="text-sm font-semibold text-foreground">
                      Spending Limit (USD)
                    </label>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Halts paid API calls once estimated costs reach this threshold. Leave empty for no limit.
                  </p>
                  <div className="relative max-w-xs">
                    <span className="absolute left-3 top-2 text-sm text-muted-foreground">
                      $
                    </span>
                    <Input
                      type="number"
                      min="0"
                      step="0.01"
                      placeholder="e.g. 5.00"
                      value={budgetUsd}
                      onChange={(e) => setBudgetUsd(e.target.value)}
                      className="pl-7"
                    />
                  </div>
                </div>

                {/* Date Range */}
                <div className="p-4 rounded-xl border border-border bg-card space-y-2">
                  <div className="flex items-center gap-2">
                    <Calendar className="h-4 w-4 text-primary" />
                    <label className="text-sm font-semibold text-foreground">
                      Collection Date Window
                    </label>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Filter mentions to a specific timeframe. Leave empty to collect from all available history.
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-md pt-1">
                    <div>
                      <span className="text-xs text-muted-foreground block mb-1">
                        Date From
                      </span>
                      <Input
                        type="date"
                        value={dateFrom}
                        onChange={(e) => setDateFrom(e.target.value)}
                      />
                    </div>
                    <div>
                      <span className="text-xs text-muted-foreground block mb-1">
                        Date To
                      </span>
                      <Input
                        type="date"
                        value={dateTo}
                        onChange={(e) => setDateTo(e.target.value)}
                      />
                    </div>
                  </div>
                </div>

                {/* Dataset Rules */}
                <div className="p-4 rounded-xl border border-border bg-card space-y-4">
                  <div className="flex items-center gap-2">
                    <RefreshCw className="h-4 w-4 text-primary" />
                    <label className="text-sm font-semibold text-foreground">
                      Dataset Caching & Freshness Rules
                    </label>
                  </div>
                  <div className="space-y-4">
                    <div>
                      <label className="text-xs font-medium text-foreground block mb-1">
                        Max Age (Days)
                      </label>
                      <Input
                        type="number"
                        min="0"
                        placeholder="e.g. 30"
                        value={maxAgeDays}
                        onChange={(e) => setMaxAgeDays(e.target.value)}
                        className="max-w-xs"
                      />
                      <span className="text-xs text-muted-foreground mt-1 block">
                        Reject mentions older than this number of days.
                      </span>
                    </div>

                    <div className="flex items-center justify-between max-w-lg pt-2 border-t border-border">
                      <div>
                        <span className="text-sm font-medium text-foreground block">
                          Require Fresh Datasets
                        </span>
                        <span className="text-xs text-muted-foreground block">
                          Only run datasets updated recently; skip stale records.
                        </span>
                      </div>
                      <Switch
                        checked={requireFresh}
                        onCheckedChange={setRequireFresh}
                      />
                    </div>

                    <div className="flex items-center justify-between max-w-lg pt-2 border-t border-border">
                      <div>
                        <span className="text-sm font-medium text-foreground block">
                          Force Re-download
                        </span>
                        <span className="text-xs text-muted-foreground block">
                          Bypass cached URL and Kaggle files and fetch a fresh copy.
                        </span>
                      </div>
                      <Switch
                        checked={refresh}
                        onCheckedChange={setRefresh}
                      />
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* STEP 4: REVIEW */}
          {currentStep === 4 && (
            <Card data-testid="step-review">
              <CardHeader>
                <CardTitle>Review & Launch</CardTitle>
                <CardDescription>
                  Confirm all collection targets and configuration before starting the run.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                {/* Companies Section */}
                <div className="p-4 rounded-xl border border-border bg-card space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-foreground">
                      Target Companies ({companies.filter((c) => c.name.trim()).length})
                    </h4>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setCurrentStep(1)}
                      className="text-xs text-primary h-7"
                    >
                      Edit
                    </Button>
                  </div>
                  <div className="divide-y divide-border">
                    {companies
                      .filter((c) => c.name.trim())
                      .map((c, i) => (
                        <div key={i} className="py-2 text-sm flex items-center justify-between">
                          <span className="font-medium text-foreground">{c.name}</span>
                          <span className="text-xs text-muted-foreground">
                            {c.industry || "No industry specified"}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>

                {/* Sources Section */}
                <div className="p-4 rounded-xl border border-border bg-card space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-foreground">
                      Selected Sources
                    </h4>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setCurrentStep(2)}
                      className="text-xs text-primary h-7"
                    >
                      Edit
                    </Button>
                  </div>
                  <div>
                    <span className="text-xs font-medium text-muted-foreground block mb-1">
                      API Platforms:
                    </span>
                    {selectedPlatforms.size === 0 ? (
                      <span className="text-xs text-muted-foreground italic">None</span>
                    ) : (
                      <div className="flex flex-wrap gap-1.5" data-testid="review-platforms">
                        {Array.from(selectedPlatforms).map((p) => (
                          <Badge key={p} variant="secondary" className="text-xs capitalize">
                            {p}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <span className="text-xs font-medium text-muted-foreground block mb-1">
                      Datasets:
                    </span>
                    {selectedDatasets.size === 0 ? (
                      <span className="text-xs text-muted-foreground italic">None</span>
                    ) : (
                      <div className="flex flex-wrap gap-1.5" data-testid="review-datasets">
                        {Array.from(selectedDatasets).map((k) => (
                          <Badge key={k} variant="secondary" className="text-xs">
                            {k}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Options Section */}
                <div className="p-4 rounded-xl border border-border bg-card space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-foreground">
                      Run Options
                    </h4>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setCurrentStep(3)}
                      className="text-xs text-primary h-7"
                    >
                      Edit
                    </Button>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <span className="text-muted-foreground block">Budget limit:</span>
                      <span className="font-medium text-foreground">
                        {budgetUsd ? formatCurrency(parseFloat(budgetUsd)) : "Unlimited"}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block">Date filter:</span>
                      <span className="font-medium text-foreground">
                        {dateFrom || dateTo ? `${dateFrom || "Start"} to ${dateTo || "Now"}` : "Full history"}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block">Freshness:</span>
                      <span className="font-medium text-foreground">
                        {requireFresh ? "Fresh only" : "Standard"}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block">Re-download:</span>
                      <span className="font-medium text-foreground">
                        {refresh ? "Forced" : "Use cached if available"}
                      </span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Stepper Navigation Buttons */}
          <div className="flex items-center justify-between pt-4 border-t border-border">
            <Button
              type="button"
              variant="outline"
              onClick={() => setCurrentStep((prev) => Math.max(1, prev - 1))}
              disabled={currentStep === 1 || submitting}
            >
              <ChevronLeft className="h-4 w-4 mr-1" />
              Back
            </Button>

            {currentStep < 4 ? (
              <Button
                type="button"
                onClick={() => setCurrentStep((prev) => Math.min(4, prev + 1))}
                disabled={!canGoNext}
                data-testid="wizard-next-btn"
              >
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            ) : (
              <Button
                type="button"
                onClick={handleStartRun}
                disabled={submitting}
                className="shadow-md"
                data-testid="submit-btn"
              >
                {submitting ? "Launching pipeline…" : "Start run"}
                <Sparkles className="h-4 w-4 ml-2" />
              </Button>
            )}
          </div>
        </div>

        {/* ── Sticky Run Summary Card (1 col) ── */}
        <div className="sticky top-20">
          <Card className="shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <Layers className="h-4 w-4 text-primary" />
                Live Run Summary
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-xs">
              <div>
                <span className="text-muted-foreground block">Target Companies</span>
                <span className="font-semibold text-foreground text-sm tabular-nums">
                  {companies.filter((c) => c.name.trim()).length} configured
                </span>
              </div>

              <Separator />

              <div>
                <span className="text-muted-foreground block">Sources Selected</span>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="outline" className="text-xs">
                    {selectedPlatforms.size} API platform{selectedPlatforms.size !== 1 ? "s" : ""}
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    {selectedDatasets.size} dataset{selectedDatasets.size !== 1 ? "s" : ""}
                  </Badge>
                </div>
              </div>

              <Separator />

              <div>
                <span className="text-muted-foreground block">Budget Cap</span>
                <span className="font-semibold text-foreground text-sm tabular-nums">
                  {budgetUsd ? formatCurrency(parseFloat(budgetUsd)) : "No limit"}
                </span>
              </div>

              <Separator />

              <div>
                <span className="text-muted-foreground block">Date Window</span>
                <span className="font-medium text-foreground">
                  {dateFrom || dateTo
                    ? `${dateFrom || "Beginning"} → ${dateTo || "Latest"}`
                    : "All history (recommended)"}
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

