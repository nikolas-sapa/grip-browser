import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "grip — Token-efficient browser SDK for AI agents",
  description: "~50 tokens per page snapshot. CDP-native, no Playwright bloat. Built for LLM agents.",
  openGraph: {
    title: "grip",
    description: "~50 tokens per page snapshot. CDP-native browser SDK for AI agents.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="font-sans antialiased bg-[#09090b] text-zinc-50 selection:bg-white/20">
        {children}
      </body>
    </html>
  );
}
