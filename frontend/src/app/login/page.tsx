"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2 } from "lucide-react";
import { verifyApiKey } from "@/lib/api";
import { setApiKey } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = key.trim();
    if (!value) {
      setError("Enter the API_SECRET_KEY from your backend .env file.");
      return;
    }

    setBusy(true);
    setError("");
    try {
      const ok = await verifyApiKey(value);
      if (!ok) {
        setError(
          "That key was rejected, or the backend is unreachable. Check API_SECRET_KEY and that the API is running.",
        );
        return;
      }
      setApiKey(value);
      router.replace("/");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-md flex-col justify-center">
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#27272a] bg-[#0f0f12]">
          <KeyRound size={18} className="text-[#818cf8]" aria-hidden="true" />
        </div>
        <div>
          <h1 className="font-mono text-xl font-semibold text-[#f4f4f5]">
            Unlock ARES AI
          </h1>
          <p className="text-xs text-[#a1a1aa]">Local, single-user session</p>
        </div>
      </div>

      <p className="mb-6 text-sm leading-6 text-[#a1a1aa]">
        Enter the <code className="text-[#d4d4d8]">API_SECRET_KEY</code> from
        your backend <code className="text-[#d4d4d8]">.env</code>. It stays in
        this browser tab and is sent as an{" "}
        <code className="text-[#d4d4d8]">X-API-Key</code> header.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div>
          <label
            htmlFor="api-key"
            className="mb-2 block text-xs font-medium uppercase tracking-wider text-[#a1a1aa]"
          >
            API key
          </label>
          <input
            id="api-key"
            name="api-key"
            type="password"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={error ? "api-key-error" : undefined}
            aria-invalid={error ? true : undefined}
            className="w-full rounded-lg border border-[#27272a] bg-[#0f0f12] px-3 py-2.5 font-mono text-sm text-[#f4f4f5] outline-none transition focus:border-[#6366f1] focus-visible:ring-2 focus-visible:ring-[#6366f1]/60"
            placeholder="Paste the key"
          />
        </div>

        {error ? (
          <p
            id="api-key-error"
            role="alert"
            className="rounded-lg border border-[#7f1d1d] bg-[#1f0a0a] px-3 py-2 text-sm text-[#fca5a5]"
          >
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#6366f1] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#4f46e5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#818cf8] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? (
            <>
              <Loader2 size={16} className="animate-spin" aria-hidden="true" />
              Checking…
            </>
          ) : (
            "Unlock dashboard"
          )}
        </button>
      </form>

      <p className="mt-6 text-xs leading-5 text-[#71717a]">
        Generate a key with{" "}
        <code className="text-[#a1a1aa]">
          python -c &quot;import secrets; print(secrets.token_urlsafe(32))&quot;
        </code>
        . The public default value is rejected by the server.
      </p>
    </div>
  );
}
