import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import RatingSummaryCard from "@/components/RatingSummaryCard";

const fetchMock = vi.fn();

function respond(data: any, status = 200) {
  fetchMock.mockResolvedValue({ ok: status < 300, status, json: async () => data });
}

const dist = (counts: number[], rated: number) =>
  [5, 4, 3, 2, 1].map((stars, i) => ({
    stars,
    count: counts[i],
    percent: rated ? Math.round((counts[i] * 1000) / rated) / 10 : 0,
  }));

const SUMMARY = {
  total_mentions: 25,
  rated_count: 20,
  unrated_count: 5,
  average: 4.8,
  distribution: dist([16, 4, 0, 0, 0], 20),
  by_platform: {
    tripadvisor: { total_mentions: 15, rated_count: 15, unrated_count: 0, average: 4.9, distribution: dist([13, 2, 0, 0, 0], 15) },
    google: { total_mentions: 5, rated_count: 5, unrated_count: 0, average: 4.6, distribution: dist([3, 2, 0, 0, 0], 5) },
    reddit: { total_mentions: 5, rated_count: 0, unrated_count: 5, average: null, distribution: dist([0, 0, 0, 0, 0], 0) },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = fetchMock;
});

describe("RatingSummaryCard", () => {
  it("shows average, per-star percentages and the unrated note", async () => {
    respond(SUMMARY);
    render(<RatingSummaryCard runId="run_1" runStatus="completed" mentionsCount={25} />);

    await waitFor(() => expect(screen.getByTestId("rating-summary-card")).toBeInTheDocument());
    expect(fetchMock.mock.calls[0][0]).toContain("/api/runs/run_1/ratings");
    expect(screen.getByTestId("rating-average")).toHaveTextContent("4.8");
    expect(screen.getByTestId("rating-average")).toHaveTextContent("20 ratings");
    expect(screen.getByTestId("rating-bar-5")).toHaveTextContent("80%");
    expect(screen.getByTestId("rating-bar-4")).toHaveTextContent("20%");
    expect(screen.getByTestId("rating-bar-1")).toHaveTextContent("0%");
    expect(screen.getByTestId("rating-unrated-note")).toHaveTextContent("5 of 25 mentions");
  });

  it("switches to a single platform's breakdown", async () => {
    respond(SUMMARY);
    render(<RatingSummaryCard runId="run_1" runStatus="completed" mentionsCount={25} />);

    await waitFor(() => expect(screen.getByTestId("rating-platform-google")).toBeInTheDocument());
    // Reddit has no ratings, so it gets no filter button
    expect(screen.queryByTestId("rating-platform-reddit")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("rating-platform-google"));
    expect(screen.getByTestId("rating-average")).toHaveTextContent("4.6");
    expect(screen.getByTestId("rating-bar-5")).toHaveTextContent("60%");
  });

  it("explains when a run has mentions but no star ratings", async () => {
    respond({
      total_mentions: 3,
      rated_count: 0,
      unrated_count: 3,
      average: null,
      distribution: dist([0, 0, 0, 0, 0], 0),
      by_platform: {},
    });
    render(<RatingSummaryCard runId="run_1" runStatus="completed" mentionsCount={3} />);
    await waitFor(() => expect(screen.getByTestId("rating-summary-empty")).toBeInTheDocument());
  });

  it("renders nothing for a run with no mentions", async () => {
    respond({ ...SUMMARY, total_mentions: 0, rated_count: 0, unrated_count: 0, average: null, by_platform: {} });
    const { container } = render(<RatingSummaryCard runId="run_1" runStatus="running" mentionsCount={0} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
