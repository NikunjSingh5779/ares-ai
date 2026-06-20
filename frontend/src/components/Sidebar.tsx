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
    <aside className="flex w-56 flex-col border-r border-r-[oklch(0.25_0_0)] bg-[oklch(0.13_0_0)]">
      {/* Brand */}
      <div className="flex items-center gap-2 border-b border-b-[oklch(0.25_0_0)] px-4 py-4">
        <div className="flex h-7 w-7 items-center justify-center rounded bg-[oklch(0.62_0.19_145)] text-xs font-bold text-black">
          A
        </div>
        <span className="font-mono text-sm font-semibold text-[oklch(0.92_0_0)]">
          ARES AI
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-2 py-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-[oklch(0.22_0.01_145)] text-[oklch(0.62_0.19_145)] font-medium"
                  : "text-[oklch(0.6_0_0)] hover:bg-[oklch(0.18_0.01_145)] hover:text-[oklch(0.92_0_0)]"
              }`}
            >
              <Icon size={16} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-t-[oklch(0.25_0_0)] px-4 py-3">
        <p className="font-mono text-[10px] text-[oklch(0.38_0_0)]">
          v0.1.0 · Paper Trading
        </p>
      </div>
    </aside>
  );
}
