"use client";

import { useEffect, useState } from "react";
import { getAgentStatus } from "@/lib/api";
import type { AgentStatusResponse } from "@/types/api";

/** Default polling interval in ms. */
const POLL_INTERVAL_MS = 1000;

/** Safety timeout — stop polling after this many ms. */
const SAFETY_TIMEOUT_MS = 60_000;

/**
 * Hook that polls the backend pipeline status while an analysis is running.
 *
 * Calls `onUpdate(status)` on each successful poll tick so the caller can
 * respond to intermediate results (e.g. update a PipelineFlow chart).
 *
 * Stops polling when:
 *   1. the pipeline completes (memory node is done)
 *   2. the safety timeout elapses (60 s)
 *   3. `running` becomes false
 */
export function usePipelinePolling(
  running: boolean,
  onUpdate?: (status: AgentStatusResponse) => void,
) {
  const [status, setStatus] = useState<AgentStatusResponse | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (!running) return;

    let cancelled = false;
    const startTime = Date.now();

    const interval = setInterval(async () => {
      // Safety timeout
      if (Date.now() - startTime > SAFETY_TIMEOUT_MS) {
        clearInterval(interval);
        setTimedOut(true);
        return;
      }

      try {
        const s = await getAgentStatus();
        if (cancelled) return;

        setStatus(s);
        onUpdate?.(s);

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
        }
      } catch {
        // Ignore transient polling errors
      }
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [running, onUpdate]);

  return { status, timedOut };
}
