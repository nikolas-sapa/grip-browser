import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { ThemeProvider } from "@/components/theme-provider";
import { BENCHMARK, endToEnd } from "@/lib/metrics";
import "./globals.css";

// The median never travels without its range, not even in metadata. Quoting the
// median alone is how the previous version of this page overstated the win.
const description = `grip is a CDP-native Python SDK that gives an AI agent a real browser it can read. ${endToEnd.median} ${endToEnd.what}, ${endToEnd.repeatRuns} across repeat runs, measured on four live scenarios of ${BENCHMARK.turnsPerScenario} turns each.`;

const title = "grip: a browser your agent can afford to look at";

export const metadata: Metadata = {
  metadataBase: new URL("https://grip-browser.vercel.app"),
  title,
  description,
  openGraph: {
    title,
    description,
    url: "https://grip-browser.vercel.app",
    siteName: "grip",
    type: "website",
  },
  twitter: { card: "summary", title, description },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <body className="font-sans antialiased">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
