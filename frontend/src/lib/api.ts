/**
 * Typed API client for Social Listening FastAPI backend.
 */

export interface HealthResponse {
  status: string;
}

export interface SourceConfigItem {
  name: string;
  method: string;
  platforms: string[];
  enabled: boolean;
  can_run: boolean;
  reason: string;
}

export interface ScrapingSiteConfigItem {
  key: string;
  name: string;
  platform: string;
  allows_scraping: boolean;
  license_note?: string | null;
  attribution?: string | null;
  can_run: boolean;
  reason: string;
}

export interface DatasetConfigItem {
  key: string;
  name: string;
  source_type: string;
  enabled: boolean;
  last_updated?: string | null;
  license_note?: string | null;
}

export interface CompanyInput {
  name: string;
  alt_spellings?: string[];
  handles?: string[];
  branches?: string[];
  industry?: string;
}

export interface SourcesInput {
  api?: string[];
  dataset_keys?: string[];
}

export interface CreateRunRequest {
  companies: CompanyInput[];
  sources?: SourcesInput;
  date_from?: string;
  date_to?: string;
  budget_usd?: number;
  run_id?: string;
  max_age_days?: number;
  require_fresh?: boolean;
  refresh?: boolean;
  scraping_allowed?: boolean;
  /** Only collect from these platforms (empty/omitted = all). */
  platform_filter?: string[];
}

export interface CreateRunResponse {
  run_id: string;
  status: string;
}

export interface TaskOutcomeItem {
  company: string;
  platform: string;
  chosen_method?: string | null;
  fallback_path: string[];
  total_items: number;
  items?: number;
  status: "ok" | "partial" | "failed" | string;
  task?: {
    company: string;
    platform: string;
  };
}

export interface InvalidCompanyItem {
  name: string;
  reasons: string[];
}

export interface PlanCandidate {
  connector: string;
  method: string;
  cost_class: string;
  reason: string;
  estimated_cost?: number;
  conditional?: boolean;
  conditions?: string[] | null;
  conditions_status?: Record<string, boolean | null> | null;
  known_conditions?: Record<string, boolean> | null;
  role?: string;
}

export interface PlanRejected {
  connector: string;
  reason: string;
}

export interface PlanDecision {
  task: {
    company: string;
    platform: string;
    [key: string]: any;
  };
  candidates: PlanCandidate[];
  rejected: PlanRejected[];
  summary: string;
}

export interface PlanResponse {
  valid_companies: string[];
  invalid_companies: InvalidCompanyItem[];
  decisions: PlanDecision[];
  notes?: string[];
  valid?: string[];
  invalid?: InvalidCompanyItem[];
}

export interface RunTotals {
  mentions_count: number;
  attempts_count: number;
  cost_usd: number;
}

export interface RunListItem {
  id: string;
  status: string;
  created_at: string;
  companies: string[];
  totals: RunTotals;
}

export interface RunDetailResponse {
  id: string;
  status: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  companies: string[];
  progress: Record<string, any>;
  counts: RunTotals;
  budget_snapshot: Record<string, any>;
  per_source_results: Record<string, any>;
  task_outcomes?: TaskOutcomeItem[] | null;
  decisions?: PlanDecision[] | null;
  invalid_companies?: InvalidCompanyItem[] | null;
  platform_filter?: {
    requested: string[];
    platforms: string[];
    free_text: string[];
    skipped_sources: string[];
    removed_mentions: number;
  } | null;
}

export interface CompactMention {
  platform: string;
  source: string;
  date?: string | null;
  short_text?: string | null;
  url?: string | null;
  method: string;
  cost: number;
  fallback_from?: string | null;
  method_used?: string;
  raw_payload?: {
    page_url?: string;
    license_note?: string;
    attribution?: string;
    raw_html?: string;
    [key: string]: any;
  } | null;
  [key: string]: any;
}

export interface PaginatedMentionsResponse {
  items: CompactMention[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CollectionAttemptItem {
  company: string;
  platform: string;
  method: string;
  status: string;
  mentions_count: number;
  cost_usd: number;
  duration_sec?: number | null;
  reason?: string | null;
  timestamp?: string | null;
  error?: string | null;
  scraping_checks?: Record<string, boolean> | null;
  pages_fetched?: number;
  pages_from_cache?: number;
  delay_used?: number;
  [key: string]: any;
}

export class ApiError extends Error {
  status: number;
  data?: any;

  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
}

async function apiFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = getApiBaseUrl().replace(/\/$/, "");
  const url = `${baseUrl}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...options.headers,
      },
    });
  } catch (err: any) {
    throw new ApiError(
      `Network error: Unable to connect to the backend server (${url}). Please verify that the backend is running.`,
      0
    );
  }

  if (!response.ok) {
    let errorDetail = "";
    let data: any = null;

    try {
      data = await response.json();
      if (data && typeof data.detail === "string") {
        errorDetail = data.detail;
      } else if (Array.isArray(data?.detail)) {
        // FastAPI 422 validation errors array
        errorDetail = data.detail
          .map((d: any) => {
            const field = Array.isArray(d.loc) ? d.loc.slice(1).join(".") : "";
            return field ? `${field}: ${d.msg}` : d.msg;
          })
          .join(", ");
      } else if (data?.message) {
        errorDetail = data.message;
      }
    } catch {
      // Non-JSON response body
    }

    if (response.status === 422) {
      throw new ApiError(
        errorDetail || "Validation error: Check your input values.",
        422,
        data
      );
    }

    if (response.status >= 500) {
      throw new ApiError(
        `Server error (${response.status}): The backend encountered an unexpected error. ${errorDetail}`,
        response.status,
        data
      );
    }

    if (response.status === 404) {
      throw new ApiError(
        errorDetail || "Resource not found (404).",
        404,
        data
      );
    }

    throw new ApiError(
      errorDetail || `Request failed with status ${response.status}`,
      response.status,
      data
    );
  }

  return response.json();
}

export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

export async function getSources(): Promise<SourceConfigItem[]> {
  return apiFetch<SourceConfigItem[]>("/api/config/sources");
}

export async function getDatasets(): Promise<DatasetConfigItem[]> {
  return apiFetch<DatasetConfigItem[]>("/api/config/datasets");
}

export async function getScrapingSites(): Promise<ScrapingSiteConfigItem[]> {
  return apiFetch<ScrapingSiteConfigItem[]>("/api/config/scraping-sites");
}

export async function createRun(data: CreateRunRequest): Promise<CreateRunResponse> {
  return apiFetch<CreateRunResponse>("/api/runs", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function planRun(data: CreateRunRequest): Promise<PlanResponse> {
  return apiFetch<PlanResponse>("/api/plan", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function getRuns(): Promise<RunListItem[]> {
  return apiFetch<RunListItem[]>("/api/runs");
}

export async function getRun(id: string): Promise<RunDetailResponse> {
  return apiFetch<RunDetailResponse>(`/api/runs/${encodeURIComponent(id)}`);
}

export async function getAttempts(
  runId: string,
  params?: { company?: string; status?: string }
): Promise<CollectionAttemptItem[]> {
  const searchParams = new URLSearchParams();
  if (params?.company) searchParams.set("company", params.company);
  if (params?.status) searchParams.set("status", params.status);
  const qs = searchParams.toString();
  return apiFetch<CollectionAttemptItem[]>(
    `/api/runs/${encodeURIComponent(runId)}/attempts${qs ? `?${qs}` : ""}`
  );
}

export async function getMentions(
  runId: string,
  params?: {
    page?: number;
    page_size?: number;
    company?: string;
    platform?: string;
    method?: string;
    full?: boolean;
  }
): Promise<PaginatedMentionsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.page) searchParams.set("page", params.page.toString());
  if (params?.page_size) searchParams.set("page_size", params.page_size.toString());
  if (params?.company) searchParams.set("company", params.company);
  if (params?.platform) searchParams.set("platform", params.platform);
  if (params?.method) searchParams.set("method", params.method);
  if (params?.full !== undefined) searchParams.set("full", params.full ? "true" : "false");

  const qs = searchParams.toString();
  return apiFetch<PaginatedMentionsResponse>(
    `/api/runs/${encodeURIComponent(runId)}/mentions${qs ? `?${qs}` : ""}`
  );
}

export function getDownloadUrl(runId: string, file: "mentions.jsonl" | "attempts.jsonl"): string {
  const baseUrl = getApiBaseUrl().replace(/\/$/, "");
  return `${baseUrl}/api/runs/${encodeURIComponent(runId)}/download?file=${file}`;
}

// ── Collection → processing gateway ──

export interface ProcessingAvailability {
  available: boolean;
  reason?: string | null;
}

export type ProcessingStatus = "not_started" | "queued" | "running" | "completed" | "failed";

export interface RunProcessingState {
  run_id: string;
  collection_status?: string;
  can_process?: boolean;
  status: ProcessingStatus | string;
  queued_at?: string;
  started_at?: string;
  finished_at?: string;
  error?: string | null;
  mentions_in?: number;
  attempts_in?: number;
  record_count?: number;
  counters?: Record<string, number>;
  total_cost_usd?: number;
}

/** URL of the data processing dashboard (Member 2, Streamlit). */
export function getProcessingDashboardUrl(): string {
  return process.env.NEXT_PUBLIC_PROCESSING_DASHBOARD_URL || "http://localhost:8501";
}

export async function getProcessingAvailability(): Promise<ProcessingAvailability> {
  return apiFetch<ProcessingAvailability>("/api/processing/status");
}

export async function getRunProcessing(runId: string): Promise<RunProcessingState> {
  return apiFetch<RunProcessingState>(`/api/runs/${encodeURIComponent(runId)}/processing`);
}

export async function startRunProcessing(runId: string): Promise<RunProcessingState> {
  return apiFetch<RunProcessingState>(`/api/runs/${encodeURIComponent(runId)}/process`, {
    method: "POST",
  });
}

// ── Star-rating summary (Amazon-style breakdown) ──

export interface StarBucket {
  stars: number;
  count: number;
  percent: number;
}

export interface RatingBreakdown {
  total_mentions: number;
  rated_count: number;
  unrated_count: number;
  average: number | null;
  distribution: StarBucket[];
}

export interface RatingSummaryResponse extends RatingBreakdown {
  by_platform: Record<string, RatingBreakdown>;
}

export async function getRatingSummary(
  runId: string,
  params?: { company?: string; platform?: string }
): Promise<RatingSummaryResponse> {
  const searchParams = new URLSearchParams();
  if (params?.company) searchParams.set("company", params.company);
  if (params?.platform) searchParams.set("platform", params.platform);
  const qs = searchParams.toString();
  return apiFetch<RatingSummaryResponse>(
    `/api/runs/${encodeURIComponent(runId)}/ratings${qs ? `?${qs}` : ""}`
  );
}

// ── Stand-alone review scraper (URL in, mentions.jsonl out) ──

export interface ScrapedReview {
  text: string;
  title?: string | null;
  rating?: number | null;
  /** thumbs up/down sites (e.g. Steam): true = Recommended, false = Not recommended */
  recommended?: boolean | null;
  author?: string | null;
  date?: string | null;
  url?: string | null;
  extraction_method: string;
}

export interface ScrapeJob {
  job_id: string;
  status: "completed" | "empty" | "failed" | string;
  url: string;
  company: string;
  created_at: string;
  reviews_count: number;
  pages_fetched: number;
  methods: Record<string, number>;
  warnings: string[];
  error?: string | null;
  download_url: string;
  mode_requested?: ScrapeMode;
  mode_used?: "static" | "browser" | string;
  reviews?: ScrapedReview[] | null;
}

/** auto: page HTML first, browser only if needed; static: HTML only; browser: always run JavaScript */
export type ScrapeMode = "auto" | "static" | "browser";

export interface ScraperCapabilities {
  browser_available: boolean;
  browser_reason: string;
}

export async function getScraperCapabilities(): Promise<ScraperCapabilities> {
  return apiFetch<ScraperCapabilities>("/api/review-scraper/capabilities");
}

export async function scrapeReviews(data: {
  url: string;
  company?: string;
  max_pages?: number;
  max_reviews?: number;
  mode?: ScrapeMode;
}): Promise<ScrapeJob> {
  return apiFetch<ScrapeJob>("/api/review-scraper", { method: "POST", body: JSON.stringify(data) });
}

export async function getScrapeJobs(): Promise<ScrapeJob[]> {
  return apiFetch<ScrapeJob[]>("/api/review-scraper");
}

export async function getScrapeJob(jobId: string): Promise<ScrapeJob> {
  return apiFetch<ScrapeJob>(`/api/review-scraper/${encodeURIComponent(jobId)}`);
}

export function getScrapeDownloadUrl(job: ScrapeJob): string {
  return `${getApiBaseUrl().replace(/\/$/, "")}${job.download_url}`;
}
