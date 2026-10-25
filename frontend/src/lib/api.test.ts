import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  ApiTimeoutError,
  getCandles,
  getSettings,
} from "@/lib/api";

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("api client", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("sends the stored API key and disables caching", async () => {
    window.sessionStorage.setItem("ares_api_key", "test-key");
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        preferences: { default_symbol: "BTC-USD", live_refresh_seconds: 10 },
        safety: {},
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getSettings();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/settings");
    expect(new Headers(init.headers).get("X-API-Key")).toBe("test-key");
    expect(init.cache).toBe("no-store");
  });

  it("builds candle query parameters and forwards the abort signal", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ symbol: "BTC-USD", candles: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await getCandles("BTC-USD", "1h", 24, controller.signal);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "http://localhost:8000/api/v1/market/candles?symbol=BTC-USD&interval=1h&limit=24",
    );
    expect(init.signal).toBeDefined();
    expect((init.signal as AbortSignal).aborted).toBe(false);
  });

  it("joins FastAPI validation messages into one error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: [{ msg: "field required" }, { msg: "bad value" }] },
          422,
        ),
      ),
    );

    await expect(getSettings()).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "field required; bad value",
    });
  });

  it("reads a nested detail message and falls back to the status text", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ detail: { message: "settings store unavailable" } }, 503),
      )
      .mockResolvedValueOnce(new Response("", { status: 502 }));
    vi.stubGlobal("fetch", fetchMock);

    const serviceError = await getSettings().catch((error: unknown) => error);
    expect(serviceError).toBeInstanceOf(ApiError);
    expect((serviceError as ApiError).message).toBe("settings store unavailable");

    const emptyError = await getSettings().catch((error: unknown) => error);
    expect(emptyError).toBeInstanceOf(ApiError);
    expect((emptyError as ApiError).status).toBe(502);
    expect((emptyError as ApiError).message).toBe("API 502 on /api/v1/settings");
  });

  it("turns a request that outlives its budget into ApiTimeoutError", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
          }),
      ),
    );

    const pending = getSettings();
    const assertion = expect(pending).rejects.toBeInstanceOf(ApiTimeoutError);
    await vi.advanceTimersByTimeAsync(30_000);
    await assertion;
  });

  it("reports a caller abort as an abort, not a timeout", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
          }),
      ),
    );
    const controller = new AbortController();
    const pending = getCandles("BTC-USD", "1d", 10, controller.signal);
    const assertion = expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });

    controller.abort();
    await assertion;
  });

  it("clears the stored key on 401", async () => {
    window.sessionStorage.setItem("ares_api_key", "expired-key");
    window.history.replaceState({}, "", "/login");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "unauthorized" }, 401)));

    await expect(getSettings()).rejects.toMatchObject({ status: 401 });
    expect(window.sessionStorage.getItem("ares_api_key")).toBeNull();
  });
});
