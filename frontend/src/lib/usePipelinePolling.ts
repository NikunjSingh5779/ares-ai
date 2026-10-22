"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { analyze, getAgentStatus } from "@/lib/api";
import type { AgentStatusResponse } from "@/types/api";

/** Default polling interval in ms. */
const POLL_INTERVAL_MS = 1000;

/** Maximum backoff after a transient status failure. */
const MAX_BACKOFF_MS = 8000;

/** Safety timeout — stop polling after this many ms. */
const SAFETY_TIMEOUT_MS = 60_000;

/**
 * Hook that owns the full trigger → poll → complete lifecycle for
 * pipeline analysis.
 *
 * Call `runAnalysis(symbol, requestText)` to trigger a new analysis.
 * The hook internally:
 *   - Calls the POST /api/v1/analyze endpoint
 *   - Polls the backend status every second after the request is accepted
 *   - Allows only one in-flight request at a time
 *   - Backs off exponentially after transient status failures
 *   - Aborts the active poll on unmount
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

  const runningRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  /** Trigger a pipeline analysis.  Returns after the backend accepts it;
   *  polling picks up the result asynchronously. */
  const runAnalysis = useCallback(
    async (symbol: string, requestText: string): Promise<void> => {
      if (runningRef.current) return;

      runningRef.current = true;
      setError(null);
      setTimedOut(false);

      try {
        await analyze(symbol, requestText);
        if (!mountedRef.current) return;
        // Polling starts only after the backend has installed the new
        // pipeline state, so an immediate poll cannot read the previous run.
        setRunning(true);
      } catch (e) {
        if (!mountedRef.current) return;
        setError(
          e instanceof Error ? e.message : `Analysis failed for ${symbol}`,
        );
        runningRef.current = false;
        setRunning(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!running) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let safetyTimer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    let pollDelay = POLL_INTERVAL_MS;

    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const finish = () => {
      if (cancelled) return;
      cancelled = true;
      clearTimer();
      if (safetyTimer !== null) {
        clearTimeout(safetyTimer);
        safetyTimer = null;
      }
      controller?.abort();
      runningRef.current = false;
      setRunning(false);
    };

    const schedule = (delay: number) => {
      if (cancelled) return;
      clearTimer();
      timer = setTimeout(() => {
        void poll();
      }, delay);
    };

    async function poll(): Promise<void> {
      if (cancelled) return;
      timer = null;

      const current = new AbortController();
      controller = current;

      try {
        const next = await getAgentStatus(current.signal);
        if (cancelled) return;

        setStatus(next);

        const pipeline = next.pipeline_status;
        const completed = pipeline?.completed_nodes ?? [];
        const failed = pipeline?.failed_nodes ?? [];
        const skipped = pipeline?.skipped_nodes ?? [];

        if (
          completed.includes("memory") ||
          failed.includes("memory") ||
          skipped.includes("memory") ||
          (pipeline?.current_node === "" && next.has_run)
        ) {
          finish();
          return;
        }

        pollDelay = POLL_INTERVAL_MS;
        schedule(pollDelay);
      } catch {
        if (cancelled || current.signal.aborted) return;

        // Transient status failures should not end the run; retry with a
        // bounded exponential backoff until the safety timeout.
        pollDelay = Math.min(pollDelay * 2, MAX_BACKOFF_MS);
        schedule(pollDelay);
      }
    }

    safetyTimer = setTimeout(() => {
      if (cancelled) return;
      setTimedOut(true);
      finish();
    }, SAFETY_TIMEOUT_MS);

    // Poll immediately instead of waiting for the first interval.
    void poll();

    return () => {
      cancelled = true;
      clearTimer();
      if (safetyTimer !== null) clearTimeout(safetyTimer);
      controller?.abort();
    };
  }, [running]);

  return { status, running, error, timedOut, runAnalysis };
}
