import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ── Mock next/navigation ──
const mockPush = vi.fn();
const mockParams = { id: "run-abc-123" };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), back: vi.fn() }),
  useParams: () => mockParams,
  usePathname: () => "/runs/run-abc-123",
}));

// ── Mock Sonner toast ──
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
  Toaster: () => <div data-testid="toaster-mock" />,
}));

// ── Helpers ──
import StatusBadge from "@/components/StatusBadge";
import type {
  SourceConfigItem,
  DatasetConfigItem,
  RunListItem,
  RunDetailResponse,
  PaginatedMentionsResponse,
  CollectionAttemptItem,
} from "@/lib/api";

function makeSources(overrides: Partial<SourceConfigItem>[] = []): SourceConfigItem[] {
  const defaults: SourceConfigItem[] = [
    { name: "reddit_api", method: "api", platforms: ["reddit"], enabled: true, can_run: true, reason: "" },
    { name: "google_places", method: "api", platforms: ["google"], enabled: true, can_run: false, reason: "Google credentials missing" },
    { name: "dataset", method: "dataset", platforms: ["other"], enabled: true, can_run: true, reason: "" },
  ];
  return defaults.map((d, i) => ({ ...d, ...overrides[i] }));
}

function makeDatasets(): DatasetConfigItem[] {
  return [
    { key: "local_reviews", name: "Local Reviews", source_type: "local", enabled: true, last_updated: "2024-01-15", license_note: "MIT" },
    { key: "hf_tweets", name: "HF Tweets", source_type: "url", enabled: true, last_updated: null, license_note: null },
    { key: "kaggle_ds", name: "Kaggle Dataset", source_type: "kaggle", enabled: false, last_updated: null, license_note: "CC BY" },
  ];
}

function makeRunListItem(overrides: Partial<RunListItem> = {}): RunListItem {
  return {
    id: "run-abc-123",
    status: "completed",
    created_at: "2024-06-01T12:00:00Z",
    companies: ["Acme Corp"],
    totals: { mentions_count: 42, attempts_count: 3, cost_usd: 1.5 },
    ...overrides,
  };
}

function makeRunDetail(overrides: Partial<RunDetailResponse> = {}): RunDetailResponse {
  return {
    id: "run-abc-123",
    status: "completed",
    created_at: "2024-06-01T12:00:00Z",
    started_at: "2024-06-01T12:00:01Z",
    finished_at: "2024-06-01T12:01:00Z",
    error: null,
    companies: ["Acme Corp"],
    progress: {},
    counts: { mentions_count: 42, attempts_count: 3, cost_usd: 1.5 },
    budget_snapshot: { limit_usd: 10, spent_usd: 1.5, platform_costs: { reddit: 1.5 } },
    per_source_results: {
      reddit_api: { status: "completed", mentions_count: 42, cost_usd: 1.5 },
    },
    ...overrides,
  };
}

function makeMentions(): PaginatedMentionsResponse {
  return {
    items: [
      {
        platform: "reddit",
        source: "r/technology",
        date: "2024-06-01",
        short_text: "Great experience with Acme Corp products!",
        text: "Full review: Great experience with Acme Corp products! Highly recommend.",
        url: "https://reddit.com/r/technology/123",
        method: "api",
        cost: 0.05,
      },
    ],
    total: 1,
    page: 1,
    page_size: 25,
    pages: 1,
  };
}

function makeAttempts(): CollectionAttemptItem[] {
  return [
    {
      company: "Acme Corp",
      platform: "reddit",
      method: "api",
      status: "completed",
      mentions_count: 42,
      cost_usd: 1.5,
      duration_sec: 2.3,
      reason: "Successful extraction",
    },
    {
      company: "Acme Corp",
      platform: "google",
      method: "api",
      status: "failed",
      mentions_count: 0,
      cost_usd: 0.0,
      duration_sec: 0.1,
      reason: "Google credentials missing",
    },
  ];
}

// ── Setup global fetch mock ──
const fetchMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = fetchMock;
});

function mockFetch(url: string, data: any, status = 200) {
  fetchMock.mockImplementation(async (reqUrl: string) => {
    if (reqUrl.includes(url)) {
      return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => data,
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

function mockFetchMultiple(handlers: Record<string, { data: any; status?: number }>) {
  fetchMock.mockImplementation(async (reqUrl: string) => {
    for (const [pattern, { data, status = 200 }] of Object.entries(handlers)) {
      if (reqUrl.includes(pattern)) {
        return {
          ok: status >= 200 && status < 300,
          status,
          json: async () => data,
        };
      }
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

// ── Tests ──

describe("StatusBadge", () => {
  it("renders the correct label and style for each status", () => {
    const { rerender, unmount } = render(<StatusBadge status="completed" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Completed");

    rerender(<StatusBadge status="failed" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Failed");

    rerender(<StatusBadge status="running" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Running");

    rerender(<StatusBadge status="queued" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Queued");

    rerender(<StatusBadge status="partial" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Partial");
    unmount();
  });

  it("renders unknown status as-is", () => {
    const { unmount } = render(<StatusBadge status="cancelled" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("cancelled");
    unmount();
  });
});

describe("ErrorBox", () => {
  it("renders error message with alert role", async () => {
    const ErrorBox = (await import("@/components/ErrorBox")).default;
    render(<ErrorBox message="Something went wrong" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("renders retry button when provided", async () => {
    const onRetry = vi.fn();
    const ErrorBox = (await import("@/components/ErrorBox")).default;
    render(<ErrorBox message="Network error" onRetry={onRetry} />);
    const retryBtn = screen.getByRole("button", { name: /retry/i });
    expect(retryBtn).toBeInTheDocument();
    fireEvent.click(retryBtn);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("EmptyState", () => {
  it("renders the message", async () => {
    const EmptyState = (await import("@/components/EmptyState")).default;
    render(<EmptyState message="Nothing here" />);
    expect(screen.getByTestId("empty-state")).toHaveTextContent("Nothing here");
  });

  it("renders action button when provided", async () => {
    const EmptyState = (await import("@/components/EmptyState")).default;
    render(
      <EmptyState
        message="No runs"
        actionHref="/runs/new"
        actionLabel="Start new run"
      />
    );
    expect(screen.getByRole("link", { name: /start new run/i })).toBeInTheDocument();
  });
});

describe("LoadingState", () => {
  it("renders default loading message", async () => {
    const LoadingState = (await import("@/components/LoadingState")).default;
    render(<LoadingState />);
    expect(screen.getByTestId("loading-state")).toHaveTextContent("Loading");
  });

  it("renders custom message", async () => {
    const LoadingState = (await import("@/components/LoadingState")).default;
    render(<LoadingState message="Fetching data…" />);
    expect(screen.getByTestId("loading-state")).toHaveTextContent("Fetching data");
  });
});

describe("Dashboard Page (/)", () => {
  it("computes stats from mocked runs and displays them", async () => {
    const runsList = [
      makeRunListItem({ id: "run-1", status: "completed", totals: { mentions_count: 10, attempts_count: 2, cost_usd: 1.0 } }),
      makeRunListItem({ id: "run-2", status: "failed", totals: { mentions_count: 0, attempts_count: 1, cost_usd: 0.0 } }),
    ];

    mockFetchMultiple({
      "/api/runs": { data: runsList },
      "/api/config/sources": { data: makeSources() },
    });

    const DashboardPage = (await import("@/app/page")).default;
    render(<DashboardPage />);

    // Total runs: 2
    await waitFor(() => {
      expect(screen.getByTestId("stat-total-runs")).toHaveTextContent("2");
    });

    // Total mentions: 10
    expect(screen.getByTestId("stat-total-mentions")).toHaveTextContent("10");

    // Total spend: $1.00
    expect(screen.getByTestId("stat-total-spend")).toHaveTextContent("$1.00");

    // Completion rate: 50%
    expect(screen.getByTestId("stat-completion-rate")).toHaveTextContent("50%");

    // Recent runs link to /runs
    expect(screen.getByRole("link", { name: /view all/i })).toHaveAttribute("href", "/runs");
  });

  it("renders empty state when there are no runs", async () => {
    mockFetchMultiple({
      "/api/runs": { data: [] },
      "/api/config/sources": { data: makeSources() },
    });

    const DashboardPage = (await import("@/app/page")).default;
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    });
    expect(screen.getByTestId("stat-total-runs")).toHaveTextContent("0");
  });
});

describe("New Run Wizard (/runs/new)", () => {
  it("blocks Next on invalid step 1 and enables when valid", async () => {
    mockFetchMultiple({
      "/api/config/sources": { data: makeSources() },
      "/api/config/datasets": { data: makeDatasets() },
    });

    const NewRunWizard = (await import("@/app/runs/new/page")).default;
    render(<NewRunWizard />);

    await waitFor(() => expect(screen.getByTestId("new-run-wizard")).toBeInTheDocument());

    const nextBtn = screen.getByTestId("wizard-next-btn");
    expect(nextBtn).toBeDisabled();

    // Enter company name
    const nameInput = screen.getByTestId("company-name-0");
    fireEvent.change(nameInput, { target: { value: "Globex" } });

    expect(nextBtn).not.toBeDisabled();
  });

  it("blocks Next on step 2 when no source is selected", async () => {
    mockFetchMultiple({
      "/api/config/sources": { data: makeSources() },
      "/api/config/datasets": { data: makeDatasets() },
    });

    const NewRunWizard = (await import("@/app/runs/new/page")).default;
    render(<NewRunWizard />);

    await waitFor(() => expect(screen.getByTestId("new-run-wizard")).toBeInTheDocument());

    // Step 1: add company
    fireEvent.change(screen.getByTestId("company-name-0"), { target: { value: "Globex" } });
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    // Now on step 2
    await waitFor(() => expect(screen.getByTestId("step-sources")).toBeInTheDocument());
    const nextBtn = screen.getByTestId("wizard-next-btn");
    expect(nextBtn).toBeDisabled();

    // Disabled source shows reason
    expect(screen.getByTestId("platform-google")).toBeDisabled();
    expect(screen.getByTestId("reason-google")).toHaveTextContent("Google credentials missing");

    // Select reddit
    fireEvent.click(screen.getByTestId("platform-reddit"));
    expect(nextBtn).not.toBeDisabled();
  });

  it("walks through to review step showing chosen sources, and submits correct payload", async () => {
    let capturedBody: any;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes("/api/config/sources")) {
        return { ok: true, status: 200, json: async () => makeSources() };
      }
      if (url.includes("/api/config/datasets")) {
        return { ok: true, status: 200, json: async () => makeDatasets() };
      }
      if (url.includes("/api/runs") && init?.method === "POST") {
        capturedBody = JSON.parse(init!.body as string);
        return { ok: true, status: 202, json: async () => ({ run_id: "new-run-wizard-123", status: "queued" }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    const NewRunWizard = (await import("@/app/runs/new/page")).default;
    render(<NewRunWizard />);

    await waitFor(() => expect(screen.getByTestId("new-run-wizard")).toBeInTheDocument());

    // Step 1: Company + handles
    fireEvent.change(screen.getByTestId("company-name-0"), { target: { value: "Acme Corp" } });
    // Expand details
    fireEvent.click(screen.getByText(/more details/i));
    fireEvent.change(screen.getByPlaceholderText(/@acme, @acmecorp/i), {
      target: { value: "@acme, @corp" },
    });
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    // Step 2: Sources
    await waitFor(() => expect(screen.getByTestId("step-sources")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("platform-reddit"));
    fireEvent.click(screen.getByTestId("dataset-local_reviews"));
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    // Step 3: Options
    await waitFor(() => expect(screen.getByTestId("step-options")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText(/e\.g\. 5\.00/i), { target: { value: "25.50" } });
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    // Step 4: Review
    await waitFor(() => expect(screen.getByTestId("step-review")).toBeInTheDocument());
    expect(screen.getByTestId("review-platforms")).toHaveTextContent("reddit");
    expect(screen.getByTestId("review-datasets")).toHaveTextContent("local_reviews");

    // Submit
    const submitBtn = screen.getByTestId("submit-btn");
    fireEvent.click(submitBtn);

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody.companies[0].name).toBe("Acme Corp");
    expect(capturedBody.companies[0].handles).toEqual(["@acme", "@corp"]);
    expect(capturedBody.sources.api).toEqual(["reddit"]);
    expect(capturedBody.sources.dataset_keys).toEqual(["local_reviews"]);
    expect(capturedBody.budget_usd).toBe(25.5);

    expect(mockPush).toHaveBeenCalledWith("/runs/new-run-wizard-123");
  });
});

describe("Runs List Page (/runs)", () => {
  it("renders runs in a table, supports search filtering and clicking", async () => {
    mockFetch("/api/runs", [
      makeRunListItem({ id: "run-abc-123", companies: ["Acme Corp"] }),
      makeRunListItem({ id: "run-xyz-456", status: "running", companies: ["Beta Inc"] }),
    ]);

    const RunsPage = (await import("@/app/runs/page")).default;
    render(<RunsPage />);

    await waitFor(() => expect(screen.getByTestId("runs-table")).toBeInTheDocument());

    expect(screen.getByText(/run-abc/)).toBeInTheDocument();
    expect(screen.getByText("Beta Inc")).toBeInTheDocument();

    // Filter by search
    const searchInput = screen.getByTestId("search-input");
    fireEvent.change(searchInput, { target: { value: "Beta" } });

    expect(screen.queryByText("Acme Corp")).not.toBeInTheDocument();
    expect(screen.getByText("Beta Inc")).toBeInTheDocument();

    // Click row
    fireEvent.click(screen.getByTestId("run-row-run-xyz-456"));
    expect(mockPush).toHaveBeenCalledWith("/runs/run-xyz-456");
  });

  it("shows empty state when no runs exist", async () => {
    mockFetch("/api/runs", []);

    const RunsPage = (await import("@/app/runs/page")).default;
    render(<RunsPage />);

    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeInTheDocument());
    expect(screen.getByTestId("empty-state")).toHaveTextContent("No runs yet");
  });
});

describe("Run Detail Page (/runs/[id])", () => {
  it("renders header, tabs, and opens mention drawer with full record", async () => {
    mockFetchMultiple({
      "/api/runs/run-abc-123/mentions": { data: makeMentions() },
      "/api/runs/run-abc-123/attempts": { data: makeAttempts() },
      "/api/runs/run-abc-123": { data: makeRunDetail() },
    });

    const RunDetailPage = (await import("@/app/runs/[id]/page")).default;
    render(<RunDetailPage />);

    await waitFor(() => expect(screen.getByTestId("run-detail")).toBeInTheDocument());
    expect(screen.getAllByText("run-abc-123").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Completed");

    // Click Mentions Tab
    const mentionsTab = screen.getByRole("tab", { name: /mentions/i });
    fireEvent.click(mentionsTab);
    fireEvent.keyDown(mentionsTab, { key: "Enter" });

    await waitFor(() => expect(screen.getByTestId("mentions-table")).toBeInTheDocument());
    expect(screen.getByText("r/technology")).toBeInTheDocument();

    // Click mention row to open detail drawer
    fireEvent.click(screen.getByTestId("mention-row-0"));

    await waitFor(() => expect(screen.getByTestId("mention-detail-drawer")).toBeInTheDocument());
    expect(screen.getByText("Text Content")).toBeInTheDocument();
    expect(screen.getByTestId("copy-json-btn")).toBeInTheDocument();
  });

  it("shows error callout for failed run", async () => {
    mockFetchMultiple({
      "/api/runs/run-abc-123/mentions": { data: { items: [], total: 0, page: 1, page_size: 25, pages: 1 } },
      "/api/runs/run-abc-123/attempts": { data: makeAttempts() },
      "/api/runs/run-abc-123": {
        data: makeRunDetail({
          status: "failed",
          error: "An unexpected error occurred during collection",
        }),
      },
    });

    const RunDetailPage = (await import("@/app/runs/[id]/page")).default;
    render(<RunDetailPage />);

    await waitFor(() => expect(screen.getByTestId("run-detail")).toBeInTheDocument());
    expect(screen.getByTestId("status-badge")).toHaveTextContent("Failed");
    expect(screen.getByTestId("error-box")).toHaveTextContent("An unexpected error occurred");
  });
});

describe("Sources Page (/sources)", () => {
  it("renders live API connectors and dataset catalogue", async () => {
    mockFetchMultiple({
      "/api/config/sources": { data: makeSources() },
      "/api/config/datasets": { data: makeDatasets() },
    });

    const SourcesPage = (await import("@/app/sources/page")).default;
    render(<SourcesPage />);

    await waitFor(() => expect(screen.getByTestId("sources-page")).toBeInTheDocument());
    expect(screen.getByText(/reddit api/i)).toBeInTheDocument();
    expect(screen.getByText(/local reviews/i)).toBeInTheDocument();
  });
});

describe("Theme Toggle", () => {
  it("persists theme preference in localStorage", async () => {
    const { ThemeProvider, ThemeToggle } = await import("@/components/ThemeProvider");

    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    const toggleBtn = screen.getByTestId("theme-toggle");
    expect(toggleBtn).toBeInTheDocument();

    // Click toggle to switch to dark theme
    fireEvent.click(toggleBtn);
    expect(localStorage.getItem("sl_theme")).toBe("dark");

    // Click toggle to switch back to light theme
    fireEvent.click(toggleBtn);
    expect(localStorage.getItem("sl_theme")).toBe("light");
  });
});
