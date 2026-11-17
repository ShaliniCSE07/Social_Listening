import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import ProcessingGateway from "@/components/ProcessingGateway";

const fetchMock = vi.fn();

type Handler = { data: any; status?: number };

function mockRoutes(routes: Record<string, Handler | ((init?: RequestInit) => Handler)>) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    for (const [pattern, h] of Object.entries(routes)) {
      if (url.endsWith(pattern)) {
        const { data, status = 200 } = typeof h === "function" ? h(init) : h;
        return { ok: status >= 200 && status < 300, status, json: async () => data };
      }
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = fetchMock;
});

const AVAILABLE = { "/api/processing/status": { data: { available: true, reason: null } } };

describe("ProcessingGateway", () => {
  it("always links to the processing dashboard in a new tab", async () => {
    mockRoutes({
      ...AVAILABLE,
      "/api/runs/run_1/processing": { data: { run_id: "run_1", status: "not_started", can_process: true } },
    });
    render(<ProcessingGateway runId="run_1" runStatus="completed" mentionsCount={10} />);

    const link = screen.getByTestId("open-processing-dashboard");
    expect(link).toHaveAttribute("href", "http://localhost:8501");
    expect(link).toHaveAttribute("target", "_blank");
    await waitFor(() => expect(screen.getByTestId("start-processing-btn")).toBeEnabled());
  });

  it("disables processing while collection is still running and makes no calls", () => {
    mockRoutes({});
    render(<ProcessingGateway runId="run_1" runStatus="running" mentionsCount={0} />);

    expect(screen.getByTestId("start-processing-btn")).toBeDisabled();
    expect(screen.getByTestId("processing-gateway-description")).toHaveTextContent(
      "Available once collection finishes."
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("disables processing for a failed collection run", async () => {
    mockRoutes({
      ...AVAILABLE,
      "/api/runs/run_1/processing": { data: { run_id: "run_1", status: "not_started", can_process: false } },
    });
    render(<ProcessingGateway runId="run_1" runStatus="failed" mentionsCount={0} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByTestId("start-processing-btn")).toBeDisabled();
  });

  it("sends the run to processing and shows the result", async () => {
    let posted = false;
    mockRoutes({
      ...AVAILABLE,
      "/api/runs/run_1/process": (init) => {
        posted = init?.method === "POST";
        return { data: { run_id: "run_1", status: "queued" }, status: 202 };
      },
      "/api/runs/run_1/processing": () =>
        posted
          ? {
              data: {
                run_id: "run_1",
                status: "completed",
                record_count: 7,
                counters: { duplicates: 2, quarantined: 1, wrong_company: 0 },
              },
            }
          : { data: { run_id: "run_1", status: "not_started", can_process: true } },
    });

    render(<ProcessingGateway runId="run_1" runStatus="completed" mentionsCount={10} />);
    await waitFor(() => expect(screen.getByTestId("start-processing-btn")).toBeEnabled());
    fireEvent.click(screen.getByTestId("start-processing-btn"));

    await waitFor(() => expect(posted).toBe(true));
    await waitFor(() => expect(screen.getByTestId("processing-step-status")).toHaveTextContent("in progress"));

    await waitFor(() => expect(screen.getByTestId("processing-summary")).toBeInTheDocument(), {
      timeout: 5000,
    });
    expect(screen.getByTestId("processing-summary")).toHaveTextContent("Records saved7");
    expect(screen.getByTestId("processing-summary")).toHaveTextContent("Duplicates removed2");
    expect(screen.queryByTestId("start-processing-btn")).not.toBeInTheDocument();
  });

  it("shows why processing is unavailable", async () => {
    mockRoutes({
      "/api/processing/status": {
        data: { available: false, reason: "MongoDB is not reachable" },
      },
      "/api/runs/run_1/processing": { data: { run_id: "run_1", status: "not_started", can_process: true } },
    });
    render(<ProcessingGateway runId="run_1" runStatus="completed" mentionsCount={10} />);

    await waitFor(() =>
      expect(screen.getByTestId("processing-unavailable")).toHaveTextContent("MongoDB is not reachable")
    );
    expect(screen.getByTestId("start-processing-btn")).toBeDisabled();
    expect(screen.getByTestId("open-processing-dashboard")).toBeInTheDocument();
  });

  it("shows the error and offers a retry when processing failed", async () => {
    mockRoutes({
      ...AVAILABLE,
      "/api/runs/run_1/processing": {
        data: { run_id: "run_1", status: "failed", error: "ValueError: bad rating" },
      },
    });
    render(<ProcessingGateway runId="run_1" runStatus="partial" mentionsCount={3} />);

    await waitFor(() => expect(screen.getByTestId("processing-error")).toHaveTextContent("bad rating"));
    expect(screen.getByTestId("start-processing-btn")).toHaveTextContent("Retry processing");
    expect(screen.getByTestId("start-processing-btn")).toBeEnabled();
  });

  it("shows the backend message when starting is refused", async () => {
    mockRoutes({
      ...AVAILABLE,
      "/api/runs/run_1/process": { data: { detail: "This run has already been processed." }, status: 409 },
      "/api/runs/run_1/processing": { data: { run_id: "run_1", status: "not_started", can_process: true } },
    });
    render(<ProcessingGateway runId="run_1" runStatus="completed" mentionsCount={3} />);
    await waitFor(() => expect(screen.getByTestId("start-processing-btn")).toBeEnabled());
    fireEvent.click(screen.getByTestId("start-processing-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("processing-action-error")).toHaveTextContent("already been processed")
    );
  });
});
