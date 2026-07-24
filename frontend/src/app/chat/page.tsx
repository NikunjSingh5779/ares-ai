"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Cpu, User, RefreshCw } from "lucide-react";
import { analyze } from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

const SUGGESTIONS = [
  "Analyze BTC-USD",
  "What's the market sentiment?",
  "Check portfolio risk exposure",
  "Run full pipeline analysis on ETH-USD",
  "Show me recent signals",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: "Hello! I'm the ARES AI trading assistant. I can analyze markets, check signals, and provide trading insights. What would you like to explore?",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async (message?: string) => {
    const text = (message || input).trim();
    if (!text || loading) return;

    setInput("");
    setError(null);

    const userMsg: ChatMessage = { role: "user", content: text, timestamp: new Date() };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      // Extract symbol from message if present
      const symbolMatch = text.match(/[A-Z]{2,5}[-]?[USD]{0,4}/i);
      const symbol = symbolMatch ? symbolMatch[0].toUpperCase() : "BTC-USD";

      const result = await analyze(symbol, text);

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: `**Analysis complete for ${symbol}**\n\nStatus: ${result.status}\nSession: ${result.session_id}\n\n${result.message}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: ChatMessage = {
        role: "assistant",
        content: `Error: ${err instanceof Error ? err.message : "Analysis failed. Please try again."}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-heading text-xl text-white">AI Chat</h1>
          <p className="text-label mt-1">Conversational Trading Interface</p>
        </div>
        <button
          onClick={() => setMessages([{
            role: "assistant",
            content: "Hello! I'm the ARES AI trading assistant. How can I help you today?",
            timestamp: new Date(),
          }])}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono"
        >
          <RefreshCw size={12} />
          Clear Chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 mb-4">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}>
            {msg.role === "assistant" && (
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#6366f1] shadow-lg shadow-[rgba(99,102,241,0.25)]">
                <Cpu size={14} className="text-black" />
              </div>
            )}
            <div
              className={`max-w-[70%] rounded-xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-[#6366f1] text-black"
                  : "card-glass"
              }`}
            >
              <p className="font-mono text-xs whitespace-pre-wrap leading-relaxed">
                {msg.content}
              </p>
              <p className={`mt-1.5 font-mono text-[10px] ${
                msg.role === "user" ? "text-[rgba(0,0,0,0.5)]" : "text-[#52525b]"
              }`}>
                {msg.timestamp.toLocaleTimeString()}
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
              <div className="flex items-center gap-2">
                <RefreshCw size={12} className="animate-spin text-[#6366f1]" />
                <span className="font-mono text-xs text-[#a1a1aa]">Analyzing...</span>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
            <p className="font-mono text-xs text-[#ef4444]">{error}</p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Suggestions */}
      <div className="flex flex-wrap gap-2 mb-3">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            onClick={() => handleSend(suggestion)}
            disabled={loading}
            className="rounded-lg border border-[rgba(255,255,255,0.08)] px-3 py-1.5 font-mono text-[10px] text-[#52525b] transition-colors hover:border-[#6366f1] hover:text-white disabled:opacity-50"
          >
            {suggestion}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about markets, analysis, or portfolio..."
          disabled={loading}
          className="flex-1 rounded-xl border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-4 py-3 font-mono text-sm text-white placeholder-[#52525b] outline-none transition-colors focus:border-[#6366f1] disabled:opacity-50"
        />
        <button
          onClick={() => handleSend()}
          disabled={!input.trim() || loading}
          className="btn-primary !px-4 !py-3 disabled:opacity-50"
        >
          <Send size={14} />
        </button>
      </div>
    </div>
  );
}
