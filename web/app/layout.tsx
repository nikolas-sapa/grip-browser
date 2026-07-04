import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://grip-browser.vercel.app"),
  title: "grip — Token-efficient browser SDK for AI agents",
  description:
    "50 tokens per page snapshot, not 12,000. CDP-native browser SDK for AI agents — no Playwright bloat.",
  openGraph: {
    title: "grip — Token-efficient browser SDK for AI agents",
    description:
      "50 tokens per page snapshot, not 12,000. CDP-native browser SDK for AI agents — no Playwright bloat.",
    url: "https://grip-browser.vercel.app",
    siteName: "grip",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "grip — Token-efficient browser SDK for AI agents",
    description:
      "50 tokens per page snapshot, not 12,000. CDP-native browser SDK for AI agents — no Playwright bloat.",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="font-sans antialiased selection:bg-white/20">
        {children}
      </body>
    </html>
  );
}
