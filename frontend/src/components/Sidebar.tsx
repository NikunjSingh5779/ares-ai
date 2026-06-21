"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  TrendingUp,
  BarChart3,
  Wallet,
  BookOpen,
  Cpu,
  Radio,
  type LucideIcon,
} from "lucide-react";

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

const navItems: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard },
  { label: "Markets", href: "/markets", icon: TrendingUp },
  { label: "Signals", href: "/signals", icon: BarChart3 },
  { label: "Portfolio", href: "/portfolio", icon: Wallet },
  { label: "Journal", href: "/journal", icon: BookOpen },
  { label: "Agents", href: "/agents", icon: Cpu },
  { label: "Live Trading", href: "/live", icon: Radio },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-56 flex-col border-r border-r-[rgba(255,255,255,0.08)] bg-[#0a0a0a]">
      {/* Brand */}
      <div className="flex items-center gap-2.5 border-b border-b-[rgba(255,255,255,0.08)] px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#6366f1] text-xs font-bold text-black shadow-lg shadow-[rgba(99,102,241,0.25)]">
          A
        </div>
        <div className="flex flex-col">
          <span className="font-sans text-sm font-bold tracking-tight text-white">
            ARES AI
          </span>
          <span className="text-[10px] font-medium tracking-wider text-[#52525b]">
            TRADING SYSTEM
          </span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-2 py-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-200 ${
                isActive
                  ? "bg-[rgba(99,102,241,0.12)] text-[#6366f1] font-semibold shadow-sm"
                  : "text-[#a1a1aa] hover:bg-[rgba(255,255,255,0.04)] hover:text-white"
              }`}
            >
              <Icon size={16} strokeWidth={isActive ? 2.5 : 1.75} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-t-[rgba(255,255,255,0.08)] px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-[#22c55e] pulse-glow" />
          <p className="font-mono text-[10px] text-[#52525b]">
            v0.1.0 · Paper Trading
          </p>
        </div>
      </div>
    </aside>
  );
}
