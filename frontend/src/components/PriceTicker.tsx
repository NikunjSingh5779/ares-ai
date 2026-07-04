"use client";

import { useState, useEffect, useRef, useCallback } from 'react';

export function PriceTicker({ symbol = 'BTCUSDT' }: { symbol?: string }) {
  const [price, setPrice] = useState<number | null>(null);
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const connect = useCallback(() => {
    const url = `wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}@ticker`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.c) {
        const currentPrice = parseFloat(data.c);
        
        setPrice(p => {
          if (p !== null && p !== currentPrice) {
            setPrevPrice(p);
            if (currentPrice > p) setFlash('up');
            else if (currentPrice < p) setFlash('down');
            
            setTimeout(() => setFlash(null), 500);
          }
          return currentPrice;
        });
      }
    };

    ws.onclose = () => {
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [symbol]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect loop on unmount
        wsRef.current.close();
      }
    };
  }, [connect]);

  if (price === null) return (
    <div className="px-3 py-1.5 rounded-lg border bg-[rgba(255,255,255,0.02)] border-[rgba(255,255,255,0.08)] flex items-center gap-2">
      <span className="text-xs text-[#a1a1aa] font-medium animate-pulse">Loading...</span>
    </div>
  );

  return (
    <div className={`px-3 py-1.5 rounded-lg border transition-colors duration-300 flex items-center gap-2 ${
      flash === 'up' 
        ? 'bg-[rgba(34,197,94,0.1)] border-[rgba(34,197,94,0.4)]' 
        : flash === 'down' 
          ? 'bg-[rgba(239,68,68,0.1)] border-[rgba(239,68,68,0.4)]' 
          : 'bg-[rgba(255,255,255,0.02)] border-[rgba(255,255,255,0.08)]'
    }`}>
      <span className="text-xs text-[#a1a1aa] font-medium">{symbol.replace('USDT', '-USD')}</span>
      <div className={`text-sm font-mono font-bold ${
        flash === 'up' 
          ? 'text-[#22c55e]' 
          : flash === 'down' 
            ? 'text-[#ef4444]' 
            : 'text-white'
      }`}>
        ${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </div>
    </div>
  );
}
