import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analyze, getAgentStatus } from "@/lib/api";
import { usePipelinePolling } from "@/lib/usePipelinePolling";
import type { AgentStatusResponse, PipelineStatus } from "@/types/api";

vi.mock("@/lib/api", () => ({
  analyze: vi.fn(),
  getAgentStatus: vi.fn(),
}));

const analyzeMock = vi.mocked(analyze);
const statusMock = vi.mocked(getAgentStatus);

const pipeline = (overrides: Partial<PipelineStatus> = {}): PipelineStatus => ({
  current_node: "quant",
  completed_nodes: ["market_analyst"],
  failed_nodes: [],
  skipped_nodes: [],
  ...overrides,
});

const agentStatus = (
  overrides: Partial<AgentStatusResponse> = {},
): AgentStatusResponse => ({
  request_id: "req-1",
  session_id: "session-1",
  symbol: "BTC-USD",
  request: "Analyze",
  request_type: "analysis",
  pipeline_status: pipeline(),
  errors: [],
  model_chain_used: {},
  degraded: false,
  total_latency_ms: 10,
  has_run: true,
  ...overrides,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("usePipelinePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("polls only after the POST is accepted and stops when memory finishes", async () => {
    const trigger = deferred<void>();
    const status = deferred<AgentStatusResponse>();
    analyzeMock.mockReturnValue(trigger.promise as never);
    statusMock.mockReturnValue(status.promise as never);

    const { result } = renderHook(() => usePipelinePolling());

    let run: Promise<void> | undefined;
    await act(async () => {
      run = result.current.runAnalysis("BTC-USD", "Analyze");
      await Promise.resolve();
    });

    expect(analyzeMock).toHaveBeenCalledWith("BTC-USD", "Analyze");
    expect(statusMock).not.toHaveBeenCalled();
    expect(result.current.running).toBe(false);

    await act(async () => {
      trigger.resolve();
      await run;
    });

    expect(result.current.running).toBe(true);
    expect(statusMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      status.resolve(
        agentStatus({ pipeline_status: pipeline({ completed_nodes: ["memory"] }) }),
      );
    });

    expect(result.current.status?.request_id).toBe("req-1");
    expect(result.current.running).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("surfaces a trigger failure without starting to poll", async () => {
    analyzeMock.mockRejectedValue(new Error("analysis unavailable"));

    const { result } = renderHook(() => usePipelinePolling());

    await act(async () => {
      await result.current.runAnalysis("BTC-USD", "Analyze");
    });

    expect(result.current.error).toBe("analysis unavailable");
    expect(result.current.running).toBe(false);
    expect(statusMock).not.toHaveBeenCalled();
  });

  it("ignores a second trigger while one is in flight", async () => {
    let resolveAnalyze: ((value: unknown) => void) | undefined;
    analyzeMock.mockReturnValue(
      new Promise((resolve) => {
        resolveAnalyze = resolve;
      }) as never,
    );

    const { result } = renderHook(() => usePipelinePolling());

    let first: Promise<void> | undefined;
    await act(async () => {
      first = result.current.runAnalysis("BTC-USD", "Analyze");
      await result.current.runAnalysis("ETH-USD", "Analyze");
    });

    expect(analyzeMock).toHaveBeenCalledTimes(1);
    expect(analyzeMock).toHaveBeenCalledWith("BTC-USD", "Analyze");

    await act(async () => {
      resolveAnalyze?.({});
      await first;
    });
  });

  it("backs off after a transient status failure and still completes", async () => {
    analyzeMock.mockResolvedValue({} as never);
    statusMock
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValue(
        agentStatus({ pipeline_status: pipeline({ completed_nodes: ["memory"] }) }),
      );

    const { result } = renderHook(() => usePipelinePolling());

    await act(async () => {
      await result.current.runAnalysis("BTC-USD", "Analyze");
    });
    await act(async () => {});

    expect(statusMock).toHaveBeenCalledTimes(1);

    // First failure schedules the next poll at 2s, not 1s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_999);
    });
    expect(statusMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(statusMock).toHaveBeenCalledTimes(2);
    expect(result.current.running).toBe(false);
  });

  it("stops at the 60 second safety timeout", async () => {
    analyzeMock.mockResolvedValue({} as never);
    statusMock.mockResolvedValue(agentStatus());

    const { result } = renderHook(() => usePipelinePolling());

    await act(async () => {
      await result.current.runAnalysis("BTC-USD", "Analyze");
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(result.current.timedOut).toBe(true);
    expect(result.current.running).toBe(false);
    expect(statusMock.mock.calls.length).toBeGreaterThan(1);
  });
});
