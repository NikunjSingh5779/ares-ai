import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "@/components/AuthGate";

const { replaceMock } = vi.hoisted(() => ({ replaceMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/live",
  useRouter: () => ({ replace: replaceMock }),
}));

vi.mock("@/components/Sidebar", () => ({
  Sidebar: () => <nav aria-label="Primary" />,
}));

describe("AuthGate", () => {
  beforeEach(() => {
    replaceMock.mockClear();
  });

  it("redirects to login when no key is stored", () => {
    render(
      <AuthGate>
        <p>protected content</p>
      </AuthGate>,
    );

    expect(replaceMock).toHaveBeenCalledWith("/login");
    expect(screen.getByRole("status")).toHaveTextContent("Checking session");
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("renders the main landmark and page when a key is stored", async () => {
    window.sessionStorage.setItem("ares_api_key", "test-key");

    render(
      <AuthGate>
        <p>protected content</p>
      </AuthGate>,
    );

    expect(await screen.findByText("protected content")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
