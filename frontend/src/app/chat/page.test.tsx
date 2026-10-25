import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatPage from "@/app/chat/page";
import { sendChatMessage } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  sendChatMessage: vi.fn(),
}));

const sendMock = vi.mocked(sendChatMessage);

const INPUT_LABEL = "Message the ARES assistant";

describe("ChatPage", () => {
  beforeEach(() => {
    sendMock.mockReset();
  });

  it("starts with a read-only empty state", () => {
    render(<ChatPage />);

    expect(
      screen.getByText(/This assistant is read-only/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(INPUT_LABEL)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Send message" }),
    ).toBeDisabled();
  });

  it("sends prior turns with the next message", async () => {
    sendMock
      .mockResolvedValueOnce({
        reply: "Risk checks exposure and drawdown.",
        model: "free-model-a",
        fallback_used: false,
      })
      .mockResolvedValueOnce({
        reply: "Both analysts must exceed 80%.",
        model: "free-model-b",
        fallback_used: true,
      });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText(INPUT_LABEL), "How does risk work?");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(
      await screen.findByText("Risk checks exposure and drawdown."),
    ).toBeInTheDocument();
    expect(screen.getByText(/free-model-a/)).toBeInTheDocument();

    await user.type(
      screen.getByLabelText(INPUT_LABEL),
      "What about consensus?",
    );
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(
      await screen.findByText("Both analysts must exceed 80%."),
    ).toBeInTheDocument();
    expect(screen.getByText(/free-model-b \(fallback\)/)).toBeInTheDocument();

    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(sendMock.mock.calls[1][0]).toEqual([
      { role: "user", content: "How does risk work?" },
      { role: "assistant", content: "Risk checks exposure and drawdown." },
      { role: "user", content: "What about consensus?" },
    ]);
  });

  it("shows a retryable error and keeps the failed user turn", async () => {
    sendMock
      .mockRejectedValueOnce(new Error("Chat model unavailable"))
      .mockResolvedValueOnce({
        reply: "The risk gate is enforced by the Risk agent.",
        model: "free-model-a",
        fallback_used: false,
      });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(
      screen.getByLabelText(INPUT_LABEL),
      "How does the risk gate work?",
    );
    await user.click(screen.getByRole("button", { name: "Send message" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Chat model unavailable");
    expect(
      within(screen.getByRole("log")).getByText("How does the risk gate work?"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Retry last message" }),
    );

    expect(
      await screen.findByText("The risk gate is enforced by the Risk agent."),
    ).toBeInTheDocument();
    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(sendMock.mock.calls[1][0]).toEqual([
      { role: "user", content: "How does the risk gate work?" },
    ]);
  });

  it("clears the conversation", async () => {
    sendMock.mockResolvedValueOnce({
      reply: "A grounded reply.",
      model: "free-model-a",
      fallback_used: false,
    });
    const user = userEvent.setup();
    render(<ChatPage />);

    await user.type(screen.getByLabelText(INPUT_LABEL), "Hello");
    await user.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByText("A grounded reply.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear Chat" }));

    expect(screen.queryByText("A grounded reply.")).not.toBeInTheDocument();
    expect(screen.getByText(/This assistant is read-only/)).toBeInTheDocument();
  });
});
