"use client";

import { useMemo } from 'react';
import {
  ComposedChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';

interface EquityCurveChartProps {
  equityCurve: number[];
}

export function EquityCurveChart({ equityCurve }: EquityCurveChartProps) {
  const chartData = useMemo(() => {
    let maxSoFar = 0;
    return equityCurve.map((equity, i) => {
      if (equity > maxSoFar) maxSoFar = equity;
      const drawdown = maxSoFar > 0 ? ((equity - maxSoFar) / maxSoFar) * 100 : 0;
      return {
        index: i,
        equity: equity,
        drawdown: drawdown,
      };
    });
  }, [equityCurve]);

  if (!equityCurve || equityCurve.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.02)]">
        <p className="text-sm text-[#52525b]">No equity curve data available</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Equity Panel */}
      <div className="h-64 rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.02)] p-4">
        <p className="text-xs font-semibold text-[#a1a1aa] mb-2 uppercase tracking-wider">Equity Curve</p>
        <div className="h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="index" hide />
              <YAxis 
                domain={['auto', 'auto']} 
                tick={{ fontSize: 11, fill: '#52525b' }} 
                stroke="rgba(255,255,255,0.05)"
                tickFormatter={(val: number) => `$${(val / 1000).toFixed(0)}k`}
                width={60}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#18181b', borderColor: 'rgba(255,255,255,0.1)' }}
                itemStyle={{ color: '#fff' }}
                labelStyle={{ display: 'none' }}
                formatter={(value: any) => [`$${Number(value).toFixed(2)}`, 'Equity']}
              />
              <Area 
                type="monotone" 
                dataKey="equity" 
                stroke="#6366f1" 
                fillOpacity={1} 
                fill="url(#colorEquity)" 
              />
              <defs>
                <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                </linearGradient>
              </defs>
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Drawdown Panel */}
      <div className="h-32 rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.02)] p-4">
        <p className="text-xs font-semibold text-[#a1a1aa] mb-2 uppercase tracking-wider">Drawdown Plot</p>
        <div className="h-[70px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="index" hide />
              <YAxis 
                domain={['auto', 0]} 
                tick={{ fontSize: 11, fill: '#52525b' }} 
                stroke="rgba(255,255,255,0.05)"
                tickFormatter={(val: number) => `${val.toFixed(0)}%`}
                width={60}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#18181b', borderColor: 'rgba(255,255,255,0.1)' }}
                itemStyle={{ color: '#fff' }}
                labelStyle={{ display: 'none' }}
                formatter={(value: any) => [`${Number(value).toFixed(2)}%`, 'Drawdown']}
              />
              <Area 
                type="monotone" 
                dataKey="drawdown" 
                stroke="#ef4444" 
                fillOpacity={1} 
                fill="url(#colorDrawdown)" 
              />
              <defs>
                <linearGradient id="colorDrawdown" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.4}/>
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0.05}/>
                </linearGradient>
              </defs>
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
