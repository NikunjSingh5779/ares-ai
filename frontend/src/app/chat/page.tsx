"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Cpu, User, RefreshCw } from "lucide-react";
import { sendChatMessage } from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  model?: string;
  fallbackUsed?: boolean;
}

/** Matches the backend's maximum bounded conversation length. */
const MAX_HISTORY = 20;

const SUGGESTIONS = [
  "How does the risk gate work?",
  "What does the 80% consensus rule mean?",
  "Explain paper trading vs live trading",
  "What should I check before promoting a strategy?",
];

const EMPTY_STATE =
  "Ask how the analysis pipeline, risk gates, paper ledger, or strategy promotion works. This assistant is read-only: it cannot place orders, change risk limits, or enable live trading.";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const requestReply = async (history: ChatMessage[]) => {
    if (loadingRef.current || history.length === 0) return;
    loadingRef.current = true;
    setLoading(true);
    setError(null);

    try {
      const result = await sendChatMessage(
        history.slice(-MAX_HISTORY).map(({ role, content }) => ({ role, content })),
      );
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result.reply,
          timestamp: new Date(),
          model: result.model,
          fallbackUsed: result.fallback_used,
        },
      ]);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Chat request failed. Please try again.",
      );
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  };

  const handleSend = (message?: string) => {
    const text = (message ?? input).trim();
    if (!text || loading || loadingRef.current) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    const history = [...messages, userMsg].slice(-MAX_HISTORY);

    setInput("");
    setMessages(history);
    void requestReply(history);
  };

  const handleRetry = () => {
    if (loading || loadingRef.current || messages.length === 0) return;
    void requestReply(messages);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const clearChat = () => {
    setMessages([]);
    setError(null);
    setInput("");
  };

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">AI Chat</h1>
          <p className="text-label mt-1">
            Read-only assistant. It cannot place trades or change risk limits.
          </p>
        </div>
        <button
          onClick={clearChat}
          disabled={messages.length === 0 || loading}
          className="btn-primary !px-3 !py-2 !text-xs !font-mono disabled:opacity-50"
        >
          <RefreshCw size={12} />
          Clear Chat
        </button>
      </div>

      <div
        className="mb-4 flex-1 space-y-3 overflow-y-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#818cf8]"
        role="log"
        aria-label="Conversation"
        aria-live="polite"
        aria-relevant="additions text"
        aria-busy={loading}
        tabIndex={0}
      >
        {messages.length === 0 && !loading && (
          <div className="card-glass rounded-xl px-5 py-6">
            <p className="font-mono text-xs leading-relaxed text-[#a1a1aa]">
              {EMPTY_STATE}
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={`${msg.role}-${i}`}
            className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}
          >
            {msg.role === "assistant" && (
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#6366f1] shadow-lg shadow-[rgba(99,102,241,0.25)]">
                <Cpu size={14} className="text-black" />
              </div>
            )}
            <div
              className={`max-w-[70%] rounded-xl px-4 py-3 ${
                msg.role === "user" ? "bg-[#6366f1] text-black" : "card-glass"
              }`}
            >
              <p className="whitespace-pre-wrap font-mono text-xs leading-relaxed">
                {msg.content}
              </p>
              <p
                className={`mt-1.5 font-mono text-[10px] ${
                  msg.role === "user"
                    ? "text-[rgba(0,0,0,0.5)]"
                    : "text-[#8b8b93]"
                }`}
              >
                {msg.timestamp.toLocaleTimeString()}
                {msg.model ? ` · ${msg.model}` : ""}
                {msg.fallbackUsed ? " (fallback)" : ""}
              </p>
            </div>
            {msg.role === "user" && (
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[rgba(255,255,255,0.1)]">
                <User size={14} className="text-[#a1a1aa]" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#6366f1] shadow-lg shadow-[rgba(99,102,241,0.25)]">
              <Cpu size={14} className="text-black" />
            </div>
            <div className="card-glass rounded-xl px-4 py-3">
              <div className="flex items-center gap-2" role="status">
                <RefreshCw size={12} className="animate-spin text-[#6366f1]" />
                <span className="font-mono text-xs text-[#a1a1aa]">
                  Thinking…
                </span>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3"
          >
            <p className="font-mono text-xs text-[#ef4444]">{error}</p>
            <button
              onClick={handleRetry}
              disabled={loading}
              className="mt-2 font-mono text-[10px] text-white underline underline-offset-2 disabled:opacity-50"
            >
              Retry last message
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="mb-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            onClick={() => handleSend(suggestion)}
            disabled={loading}
            className="rounded-lg border border-[rgba(255,255,255,0.08)] px-3 py-1.5 font-mono text-[10px] text-[#8b8b93] transition-colors hover:border-[#6366f1] hover:text-white disabled:opacity-50"
          >
            {suggestion}
          </button>
        ))}
      </div>

      <div className="flex gap-2">
        <label htmlFor="chat-input" className="sr-only">
          Message the ARES assistant
        </label>
        <input
          id="chat-input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about the pipeline, risk gates, or strategy promotion..."
          maxLength={4000}
          disabled={loading}
          aria-describedby="chat-input-hint"
          className="flex-1 rounded-xl border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-4 py-3 font-mono text-sm text-white placeholder-[#8b8b93] outline-none transition-colors focus:border-[#6366f1] disabled:opacity-50"
        />
        <span id="chat-input-hint" className="sr-only">
          Press Enter to send. The assistant is read-only and cannot place trades.
        </span>
        <button
          onClick={() => handleSend()}
          disabled={!input.trim() || loading}
          aria-label="Send message"
          className="btn-primary !px-4 !py-3 disabled:opacity-50"
        >
          <Send size={14} />
        </button>
      </div>
    </div>
  );
}
