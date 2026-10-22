"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { getApiKey } from "@/lib/auth";

/**
 * Client-side gate for the local single-user dashboard.
 *
 * sessionStorage is intentionally tab-scoped: opening a new tab asks for the
 * key again rather than leaving a long-lived credential in localStorage.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/login";
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (isLogin) {
      setReady(true);
      return;
    }
    if (!getApiKey()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [isLogin, router]);

  if (isLogin) {
    return (
      <main id="main-content" tabIndex={-1} className="flex-1 overflow-y-auto p-6">
        {children}
      </main>
    );
  }

  if (!ready) {
    return (
      <main
        id="main-content"
        tabIndex={-1}
        className="flex flex-1 items-center justify-center p-6"
        role="status"
        aria-live="polite"
      >
        Checking session…
      </main>
    );
  }

  return (
    <>
      <Sidebar />
      <main id="main-content" tabIndex={-1} className="flex-1 overflow-y-auto p-6">
        {children}
      </main>
    </>
  );
}
