"use client";

import { useEffect, useState } from "react";
import { analyze, getAgentStatus } from "@/lib/api";
import type { AgentStatusResponse } from "@/types/api";

/** Default polling interval in ms. */
const POLL_INTERVAL_MS = 1000;

/** Safety timeout — stop polling after this many ms. */
const SAFETY_TIMEOUT_MS = 60_000;

/**
 * Hook that owns the full trigger → poll → complete lifecycle for
 * pipeline analysis.
 *
 * Call `runAnalysis(symbol, requestText)` to trigger a new analysis.
 * The hook internally:
 *   - Calls the POST /api/v1/analyze endpoint
 *   - Polls the backend status every second
 *   - Detects pipeline completion (when the "memory" node is done)
 *   - Resets `running` to false on completion or on a 60s safety timeout
 *
 * Pages that use this hook no longer manage their own `running` state
 * or call `analyze()` directly.
 */
export function usePipelinePolling() {
  const [status, setStatus] = useState<AgentStatusResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  /** Trigger a pipeline analysis.  Returns immediately; polling picks up
   *  the result asynchronously. */
  async function runAnalysis(symbol: string, requestText: string) {
    setError(null);
    setTimedOut(false);
    setRunning(true);
    try {
      await analyze(symbol, requestText);
    } catch {
      setError(`Analysis failed for ${symbol}`);
      setRunning(false);
    }
  }

  useEffect(() => {
    if (!running) return;

    let cancelled = false;
    const startTime = Date.now();

    const interval = setInterval(async () => {
      // Safety timeout — stop polling and surface the error
      if (Date.now() - startTime > SAFETY_TIMEOUT_MS) {
        clearInterval(interval);
        setTimedOut(true);
        setRunning(false);
        return;
      }

      try {
        const s = await getAgentStatus();
        if (cancelled) return;

        setStatus(s);

        // Check if pipeline is finished (memory is the last node)
        const completed = s.pipeline_status?.completed_nodes ?? [];
        const failed = s.pipeline_status?.failed_nodes ?? [];
        const skipped = s.pipeline_status?.skipped_nodes ?? [];

        if (
          completed.includes("memory") ||
          failed.includes("memory") ||
          skipped.includes("memory") ||
          (s.pipeline_status?.current_node === "" && s.has_run)
        ) {
          clearInterval(interval);
          setRunning(false);
        }
      } catch {
        // Ignore transient polling errors
      }
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [running]);

  return { status, running, error, timedOut, runAnalysis };
}
