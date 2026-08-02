import type { Metadata } from "next";
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import "@fontsource/jetbrains-mono/700.css";
import { Sidebar } from "@/components/Sidebar";
import "./globals.css";

const style = {
  "--font-space-grotesk": "Space Grotesk",
  "--font-jetbrains-mono": "JetBrains Mono",
} as React.CSSProperties;

export const metadata: Metadata = {
  title: "ARES AI — Trading Dashboard",
  description:
    "Autonomous Research Execution System — Multi-Agent Trading Intelligence",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className="dark"
      style={style}
      suppressHydrationWarning
    >
      <body className="flex h-screen overflow-hidden bg-[var(--color-bg)]" suppressHydrationWarning>
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </body>
    </html>
  );
}
