import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import ScraperPage from "@/app/scraper/page";

const fetchMock = vi.fn();

const JOB = {
  job_id: "scrape_abcd1234",
  status: "completed",
  url: "https://hotel.example/reviews",
  company: "Hotel Sunrise",
  created_at: "2026-11-24T10:00:00Z",
  reviews_count: 2,
  pages_fetched: 1,
  methods: { heuristic: 2 },
  warnings: [],
  error: null,
  download_url: "/api/review-scraper/scrape_abcd1234/download",
  reviews: [
    { text: "Spotless rooms and great breakfast.", rating: 5, author: "Priya", date: "2026-03-02", extraction_method: "heuristic" },
    { text: "Noisy at night.", rating: 3, author: "John", extraction_method: "heuristic" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = fetchMock;
});

function route(handlers: Record<string, (init?: RequestInit) => any>) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    for (const [suffix, h] of Object.entries(handlers)) {
      if (url.endsWith(suffix)) {
        const { data, status = 200 } = h(init);
        return { ok: status < 300, status, json: async () => data };
      }
    }
    return { ok: true, status: 200, json: async () => [] };
  });
}

describe("Web Scraper page", () => {
  it("disables the button until a valid URL is entered", () => {
    route({ "/api/review-scraper": () => ({ data: [] }) });
    render(<ScraperPage />);
    expect(screen.getByTestId("scrape-submit")).toBeDisabled();
    fireEvent.change(screen.getByTestId("scrape-url"), { target: { value: "https://hotel.example/reviews" } });
    expect(screen.getByTestId("scrape-submit")).toBeEnabled();
  });

  it("scrapes a URL and shows reviews, average and the download link", async () => {
    route({
      "/api/review-scraper": (init) => (init?.method === "POST" ? { data: JOB } : { data: [] }),
    });
    render(<ScraperPage />);
    fireEvent.change(screen.getByTestId("scrape-url"), { target: { value: "https://hotel.example/reviews" } });
    fireEvent.change(screen.getByTestId("scrape-company"), { target: { value: "Hotel Sunrise" } });
    fireEvent.click(screen.getByTestId("scrape-submit"));

    await waitFor(() => expect(screen.getByTestId("scrape-result")).toBeInTheDocument());
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post![1].body)).toMatchObject({ url: "https://hotel.example/reviews", company: "Hotel Sunrise", max_pages: 3 });

    expect(screen.getByTestId("scrape-stats")).toHaveTextContent("2 reviews");
    expect(screen.getByTestId("scrape-average")).toHaveTextContent("4.0 average from 2 rated");
    expect(screen.getByTestId("scrape-reviews")).toHaveTextContent("Spotless rooms and great breakfast.");
    expect(screen.getByTestId("scrape-download").getAttribute("href")).toBe(
      "http://localhost:8000/api/review-scraper/scrape_abcd1234/download"
    );
  });

  it("shows the error and no download for a failed scrape", async () => {
    route({
      "/api/review-scraper": (init) =>
        init?.method === "POST"
          ? { data: { ...JOB, status: "failed", reviews_count: 0, reviews: [], error: "The website returned HTTP 403." } }
          : { data: [] },
    });
    render(<ScraperPage />);
    fireEvent.change(screen.getByTestId("scrape-url"), { target: { value: "https://blocked.example/" } });
    fireEvent.click(screen.getByTestId("scrape-submit"));
    await waitFor(() => expect(screen.getByTestId("scrape-error")).toHaveTextContent("HTTP 403"));
    expect(screen.queryByTestId("scrape-download")).not.toBeInTheDocument();
  });

  it("sends the chosen mode and shows how the page was read", async () => {
    route({
      "/api/review-scraper/capabilities": () => ({ data: { browser_available: true, browser_reason: "ready" } }),
      "/api/review-scraper": (init) =>
        init?.method === "POST" ? { data: { ...JOB, mode_requested: "browser", mode_used: "browser" } } : { data: [] },
    });
    render(<ScraperPage />);
    expect(screen.getByTestId("scrape-mode-auto")).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByTestId("scrape-mode-browser"));
    expect(screen.getByTestId("scrape-mode-help")).toHaveTextContent("headless browser");
    fireEvent.change(screen.getByTestId("scrape-url"), { target: { value: "https://shop.example/item" } });
    fireEvent.click(screen.getByTestId("scrape-submit"));

    await waitFor(() => expect(screen.getByTestId("scrape-mode-used")).toHaveTextContent("rendered in browser"));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post![1].body).mode).toBe("browser");
  });

  it("disables browser mode when it is not installed", async () => {
    route({
      "/api/review-scraper/capabilities": () => ({ data: { browser_available: false, browser_reason: "Install Playwright." } }),
      "/api/review-scraper": () => ({ data: [] }),
    });
    render(<ScraperPage />);
    await waitFor(() => expect(screen.getByTestId("scrape-browser-missing")).toHaveTextContent("Install Playwright."));
    expect(screen.getByTestId("scrape-mode-browser")).toBeDisabled();
  });

  it("shows Recommended / Not recommended for thumbs-style reviews", async () => {
    const steamJob = {
      ...JOB,
      reviews: [
        { text: "Brilliant puzzles and a funny story.", recommended: true, author: "Nova", extraction_method: "repeated_blocks" },
        { text: "Crashed twice on my laptop.", recommended: false, author: "Orbit", extraction_method: "repeated_blocks" },
      ],
    };
    route({ "/api/review-scraper": (init) => (init?.method === "POST" ? { data: steamJob } : { data: [] }) });
    render(<ScraperPage />);
    fireEvent.change(screen.getByTestId("scrape-url"), { target: { value: "https://store.example/app/1" } });
    fireEvent.click(screen.getByTestId("scrape-submit"));
    await waitFor(() => expect(screen.getAllByTestId("scrape-recommended")).toHaveLength(2));
    const labels = screen.getAllByTestId("scrape-recommended").map((e) => e.textContent);
    expect(labels).toEqual(["Recommended", "Not recommended"]);
  });
});
