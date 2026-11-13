import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom";
import React from "react";

// Mock next/navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), back: vi.fn() }),
  useParams: () => ({ id: "run-test-scraping" }),
  usePathname: () => "/runs/run-test-scraping",
}));

// Mock sonner
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
  Toaster: () => <div data-testid="toaster-mock" />,
}));

import NewRunWizardPage from "@/app/runs/new/page";
import RunDetailPage from "@/app/runs/[id]/page";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = fetchMock;
});

afterEach(() => {
  cleanup();
});

function mockFetchRouter(handlers: Record<string, { data: any; status?: number } | ((body?: any) => { data: any; status?: number })>) {
  // Sort patterns by length descending so longer/more specific URLs match first
  const sortedPatterns = Object.entries(handlers).sort((a, b) => b[0].length - a[0].length);

  fetchMock.mockImplementation(async (reqUrl: string, options: any = {}) => {
    for (const [pattern, handler] of sortedPatterns) {
      if (reqUrl.includes(pattern)) {
        let res;
        if (typeof handler === "function") {
          const body = options.body ? JSON.parse(options.body) : undefined;
          res = handler(body);
        } else {
          res = handler;
        }
        const status = res.status ?? 200;
        return {
          ok: status >= 200 && status < 300,
          status,
          json: async () => res.data,
        };
      }
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

describe("Stage 3: Web Scraping Frontend Integration", () => {
  // 1. Scraping switch is off by default and sends flag when on
  it("scraping switch is off by default and sends scraping_allowed flag when on", async () => {
    let capturedPlanPayload: any = null;
    let capturedCreatePayload: any = null;

    mockFetchRouter({
      "/api/config/sources": {
        data: [
          { name: "reddit_api", method: "api", platforms: ["reddit"], enabled: true, can_run: true, reason: "" },
          { name: "scraping", method: "scraping", platforms: ["news_blog"], enabled: true, can_run: true, reason: "" },
        ],
      },
      "/api/config/datasets": { data: [] },
      "/api/plan": (body) => {
        capturedPlanPayload = body;
        return {
          data: {
            valid_companies: ["Acme Corp"],
            invalid_companies: [],
            decisions: [
              {
                task: { company: "Acme Corp", platform: "reddit" },
                candidates: [
                  { connector: "reddit_api", method: "api", cost_class: "free", reason: "Direct", conditional: false },
                ],
                rejected: [],
                summary: "Selected reddit_api",
              },
            ],
          },
        };
      },
      "/api/runs": (body) => {
        capturedCreatePayload = body;
        return { data: { run_id: "new-run-123", status: "queued" } };
      },
    });

    render(<NewRunWizardPage />);

    // Wait for sources to load
    await waitFor(() => {
      expect(screen.getByTestId("company-name-0")).toBeInTheDocument();
    });

    // Fill company name on step 1
    fireEvent.change(screen.getByTestId("company-name-0"), { target: { value: "Acme Corp" } });

    // Next to Step 2
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    // Check Sources step
    await waitFor(() => {
      expect(screen.getByTestId("card-web-scraping")).toBeInTheDocument();
    });

    const switchEl = screen.getByTestId("switch-scraping-allowed");
    expect(switchEl).toHaveAttribute("aria-checked", "false");
    expect(screen.getByTestId("scraping-disabled-caption")).toHaveTextContent("Turn on scraping to use these sites");

    // Select an API platform so step 2 is valid
    fireEvent.click(screen.getByTestId("platform-card-reddit"));

    // Toggle scraping on
    fireEvent.click(switchEl);
    expect(switchEl).toHaveAttribute("aria-checked", "true");

    // Next to Step 3 (Options)
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    // Next to Step 4 (Review / Plan)
    await waitFor(() => {
      expect(screen.getByTestId("step-options")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    // Plan preview should have been called with scraping_allowed: true
    await waitFor(() => {
      expect(capturedPlanPayload).not.toBeNull();
      expect(capturedPlanPayload.scraping_allowed).toBe(true);
    });

    // Launch run
    fireEvent.click(screen.getByTestId("submit-btn"));
    await waitFor(() => {
      expect(capturedCreatePayload).not.toBeNull();
      expect(capturedCreatePayload.scraping_allowed).toBe(true);
    });
  });

  // 2. A site with a reason renders disabled with that reason
  it("renders a site with a backend reason as disabled with that reason", async () => {
    mockFetchRouter({
      "/api/config/sources": {
        data: [
          { name: "reddit_api", method: "api", platforms: ["reddit"], enabled: true, can_run: true, reason: "" },
          { name: "hackernews", method: "scraping", platforms: ["news_blog"], enabled: true, can_run: false, reason: "SCRAPER_CONTACT not set" },
        ],
      },
      "/api/config/datasets": { data: [] },
    });

    render(<NewRunWizardPage />);

    await waitFor(() => {
      expect(screen.getByTestId("company-name-0")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("company-name-0"), { target: { value: "Acme Corp" } });
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("card-web-scraping")).toBeInTheDocument();
    });

    const siteCard = screen.getByTestId("scraping-site-hackernews");
    expect(siteCard).toBeInTheDocument();
    expect(siteCard).toHaveTextContent("SCRAPER_CONTACT not set");
    expect(siteCard.className).toContain("cursor-not-allowed");
  });

  // 3. Plan preview shows three conditions with the right icons
  it("plan preview shows three conditions with right icons and state text", async () => {
    mockFetchRouter({
      "/api/config/sources": {
        data: [
          { name: "reddit_api", method: "api", platforms: ["reddit"], enabled: true, can_run: true, reason: "" },
          { name: "scraping", method: "scraping", platforms: ["news_blog"], enabled: true, can_run: true, reason: "" },
        ],
      },
      "/api/config/datasets": { data: [] },
      "/api/plan": {
        data: {
          valid_companies: ["Acme Corp"],
          invalid_companies: [],
          decisions: [
            {
              task: { company: "Acme Corp", platform: "news_blog" },
              candidates: [
                {
                  connector: "scraping",
                  method: "scraping",
                  cost_class: "free",
                  role: "fallback",
                  reason: "Fallback web scraping",
                  conditional: true,
                  conditions: ["site_policy_allows", "other_methods_failed", "below_min_threshold"],
                  known_conditions: { site_policy_allows: true },
                  conditions_status: {
                    site_policy_allows: true,
                    other_methods_failed: null,
                    below_min_threshold: null,
                  },
                },
              ],
              rejected: [],
              summary: "Selected scraping as conditional fallback",
            },
          ],
        },
      },
    });

    render(<NewRunWizardPage />);

    await waitFor(() => {
      expect(screen.getByTestId("company-name-0")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("company-name-0"), { target: { value: "Acme Corp" } });
    fireEvent.click(screen.getByTestId("wizard-next-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("card-web-scraping")).toBeInTheDocument();
    });

    // Turn on scraping and select platform
    fireEvent.click(screen.getByTestId("platform-card-reddit"));
    fireEvent.click(screen.getByTestId("switch-scraping-allowed"));

    fireEvent.click(screen.getByTestId("wizard-next-btn")); // step 3
    await waitFor(() => expect(screen.getByTestId("step-options")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("wizard-next-btn")); // step 4

    await waitFor(() => {
      expect(screen.getByTestId("scraping-conditions-panel")).toBeInTheDocument();
    });

    // Check conditions
    const policyCond = screen.getByTestId("condition-site-policy");
    expect(policyCond).toHaveTextContent("Site policy allows scraping (known now: yes)");
    expect(policyCond.querySelector("svg")).toBeInTheDocument(); // tick icon

    const otherMethodsCond = screen.getByTestId("condition-other-methods");
    expect(otherMethodsCond).toHaveTextContent("Other methods failed");
    expect(otherMethodsCond).toHaveTextContent("Checked during the run");

    const thresholdCond = screen.getByTestId("condition-threshold");
    expect(thresholdCond).toHaveTextContent("Results below the minimum");
    expect(thresholdCond).toHaveTextContent("Checked during the run");
  });

  // 4. Skipped attempt shows its reason in Overview tab
  it("skipped attempt shows its reason in Overview tab", async () => {
    mockFetchRouter({
      "/api/runs/run-test-scraping": {
        data: {
          id: "run-test-scraping",
          status: "completed",
          created_at: "2024-06-01T12:00:00Z",
          companies: ["Acme Corp"],
          counts: { mentions_count: 10, attempts_count: 2, cost_usd: 0 },
          budget_snapshot: {},
          per_source_results: {},
          task_outcomes: [
            {
              company: "Acme Corp",
              platform: "news_blog",
              status: "ok",
              chosen_method: "dataset",
              fallback_path: ["dataset", "scraping"],
              total_items: 10,
              items: 10,
            },
          ],
        },
      },
      "/api/runs/run-test-scraping/attempts": {
        data: [
          {
            company: "Acme Corp",
            platform: "news_blog",
            method: "scraping",
            status: "skipped",
            mentions_count: 0,
            cost_usd: 0,
            reason: "below threshold condition failed: 10 >= 5",
            scraping_checks: {
              site_policy_allows: true,
              other_methods_failed: false,
              below_min_threshold: false,
            },
          },
        ],
      },
      "/api/runs/run-test-scraping/mentions": {
        data: { items: [], total: 0, page: 1, page_size: 25, pages: 1 },
      },
    });

    render(<RunDetailPage />);

    await waitFor(() => {
      expect(screen.getByTestId("how-each-source-collected-card")).toBeInTheDocument();
    });

    const skippedReasonEl = screen.getByTestId("scraping-skipped-reason");
    expect(skippedReasonEl).toHaveTextContent("Skipped: below threshold condition failed: 10 >= 5");

    // Three checks rows in Overview
    expect(screen.getByTestId("check-site-policy")).toHaveTextContent("Site policy permits scraping");
    expect(screen.getByTestId("check-other-methods")).toHaveTextContent("A prior collection method succeeded");
    expect(screen.getByTestId("check-below-threshold")).toHaveTextContent("Collected items already meet or exceed the threshold");
  });

  // 5. scraping_checks chips render in Attempts tab
  it("renders scraping_checks chips in Attempts tab", async () => {
    mockFetchRouter({
      "/api/runs/run-test-scraping": {
        data: {
          id: "run-test-scraping",
          status: "completed",
          created_at: "2024-06-01T12:00:00Z",
          companies: ["Acme Corp"],
          counts: { mentions_count: 0, attempts_count: 1, cost_usd: 0 },
          budget_snapshot: {},
          per_source_results: {},
        },
      },
      "/api/runs/run-test-scraping/attempts": {
        data: [
          {
            company: "Acme Corp",
            platform: "other",
            method: "scraping",
            status: "skipped",
            mentions_count: 0,
            cost_usd: 0,
            reason: "Domain policy disallows scraping",
            scraping_checks: {
              site_policy_allows: false,
              other_methods_failed: true,
              below_min_threshold: true,
            },
          },
        ],
      },
      "/api/runs/run-test-scraping/mentions": {
        data: { items: [], total: 0, page: 1, page_size: 25, pages: 1 },
      },
    });

    render(<RunDetailPage />);

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /attempts/i })).toBeInTheDocument();
    });

    // Switch to Attempts tab
    const attemptsTab = screen.getByRole("tab", { name: /attempts/i });
    fireEvent.click(attemptsTab);
    fireEvent.keyDown(attemptsTab, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByTestId("attempt-scraping-checks")).toBeInTheDocument();
    });

    expect(screen.getByTestId("chip-policy")).toHaveTextContent("policy");
    expect(screen.getByTestId("chip-other-methods")).toHaveTextContent("other methods");
    expect(screen.getByTestId("chip-threshold")).toHaveTextContent("threshold");
  });

  // 6. raw_html is escaped, not rendered as live HTML
  it("escapes raw_html inside a code block and does not render it as live HTML", async () => {
    const maliciousHtml = "<script>alert('xss')</script><div id='injected-elem'>Dangerous Text</div>";

    mockFetchRouter({
      "/api/runs/run-test-scraping": {
        data: {
          id: "run-test-scraping",
          status: "completed",
          created_at: "2024-06-01T12:00:00Z",
          companies: ["Acme Corp"],
          counts: { mentions_count: 1, attempts_count: 1, cost_usd: 0 },
          budget_snapshot: {},
          per_source_results: {},
        },
      },
      "/api/runs/run-test-scraping/attempts": { data: [] },
      "/api/runs/run-test-scraping/mentions": {
        data: {
          items: [
            {
              platform: "news_blog",
              source: "hackernews",
              date: "2024-06-01",
              short_text: "Acme Corp launched v2",
              text: "Acme Corp launched v2 on Hacker News",
              method: "scraping",
              cost: 0,
              fallback_from: "dataset",
              raw_payload: {
                page_url: "https://news.ycombinator.com/item?id=123",
                license_note: "Public web content",
                attribution: "Hacker News item 123",
                raw_html: maliciousHtml,
              },
            },
          ],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        },
      },
    });

    render(<RunDetailPage />);

    // Switch to Mentions tab
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /mentions/i })).toBeInTheDocument();
    });
    const mentionsTab = screen.getByRole("tab", { name: /mentions/i });
    fireEvent.click(mentionsTab);
    fireEvent.keyDown(mentionsTab, { key: "Enter" });

    // Check method badge and fallback badge
    await waitFor(() => {
      expect(screen.getByTestId("method-badge-scraped")).toHaveTextContent("Web scraped");
      expect(screen.getByTestId("fallback-badge")).toHaveTextContent("via fallback");
    });

    // Click mention row to open drawer
    fireEvent.click(screen.getByTestId("mention-row-0"));

    await waitFor(() => {
      expect(screen.getByTestId("mention-detail-drawer")).toBeInTheDocument();
    });

    // Check page_url, license_note, attribution
    expect(screen.getByTestId("scraped-page-url")).toHaveTextContent("https://news.ycombinator.com/item?id=123");
    expect(screen.getByTestId("scraped-license-note")).toHaveTextContent("Public web content");
    expect(screen.getByTestId("scraped-attribution")).toHaveTextContent("Hacker News item 123");

    // Click Original HTML toggle
    fireEvent.click(screen.getByTestId("toggle-raw-html-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("raw-html-content")).toBeInTheDocument();
    });

    // Verify it contains escaped text
    expect(screen.getByTestId("raw-html-content")).toHaveTextContent(maliciousHtml);

    // Verify no live element was injected into DOM
    expect(document.getElementById("injected-elem")).toBeNull();
  });

  // 7. Privacy notice appears only when scraped mentions exist
  it("privacy notice appears only when scraped mentions exist", async () => {
    // 7A: Non-scraped run
    mockFetchRouter({
      "/api/runs/run-test-scraping": {
        data: {
          id: "run-test-scraping",
          status: "completed",
          created_at: "2024-06-01T12:00:00Z",
          companies: ["Acme Corp"],
          counts: { mentions_count: 5, attempts_count: 1, cost_usd: 0.1 },
          budget_snapshot: {},
          per_source_results: {},
        },
      },
      "/api/runs/run-test-scraping/attempts": { data: [] },
      "/api/runs/run-test-scraping/mentions": {
        data: {
          items: [{ platform: "reddit", source: "r/tech", method: "api", cost: 0.1 }],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        },
      },
    });

    const { unmount } = render(<RunDetailPage />);

    await waitFor(() => {
      expect(screen.getByTestId("run-detail")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("privacy-notice-card")).toBeNull();
    unmount();

    // 7B: Run with scraped mentions
    mockFetchRouter({
      "/api/runs/run-test-scraping": {
        data: {
          id: "run-test-scraping",
          status: "completed",
          created_at: "2024-06-01T12:00:00Z",
          companies: ["Acme Corp"],
          counts: { mentions_count: 1, attempts_count: 1, cost_usd: 0 },
          budget_snapshot: {},
          per_source_results: {},
        },
      },
      "/api/runs/run-test-scraping/attempts": { data: [] },
      "/api/runs/run-test-scraping/mentions": {
        data: {
          items: [{ platform: "news_blog", source: "hackernews", method: "scraping", cost: 0 }],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        },
      },
    });

    render(<RunDetailPage />);

    await waitFor(() => {
      expect(screen.getByTestId("privacy-notice-card")).toBeInTheDocument();
    });

    expect(screen.getByTestId("privacy-notice-card")).toHaveTextContent(
      "Scraped content can include usernames. Personal details are masked in the processing step before sharing."
    );
  });

  // 8. An older run without the new fields still renders
  it("an older run without the new fields still renders cleanly", async () => {
    mockFetchRouter({
      "/api/runs/run-test-scraping": {
        data: {
          id: "run-legacy-001",
          status: "completed",
          created_at: "2023-01-01T00:00:00Z",
          companies: ["Legacy Co"],
          counts: { mentions_count: 3, attempts_count: 1, cost_usd: 0 },
          budget_snapshot: {},
          per_source_results: {},
          // No task_outcomes, no scraping fields
        },
      },
      "/api/runs/run-test-scraping/attempts": {
        data: [
          {
            company: "Legacy Co",
            platform: "reddit",
            method: "api",
            status: "completed",
            mentions_count: 3,
            cost_usd: 0,
            // No scraping_checks
          },
        ],
      },
      "/api/runs/run-test-scraping/mentions": {
        data: {
          items: [
            {
              platform: "reddit",
              source: "r/legacy",
              method: "api",
              cost: 0,
              // No raw_payload, no fallback_from
            },
          ],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
        },
      },
    });

    render(<RunDetailPage />);

    await waitFor(() => {
      expect(screen.getByTestId("run-detail")).toBeInTheDocument();
      expect(screen.getAllByText("run-legacy-001").length).toBeGreaterThanOrEqual(1);
    });

    // Overview tab should render without error
    expect(screen.queryByTestId("privacy-notice-card")).toBeNull();
  });
});

