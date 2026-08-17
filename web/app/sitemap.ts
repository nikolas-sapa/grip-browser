import type { MetadataRoute } from "next";
import { BENCHMARK } from "@/lib/metrics";

// lastModified is the benchmark date, not deploy time: it's the real thing
// that last changed the content of "/". /changelog has no equivalent source
// yet, so it ships without one rather than a made-up timestamp.
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: "https://grip-browser.vercel.app/",
      lastModified: BENCHMARK.date,
      priority: 1,
    },
    {
      url: "https://grip-browser.vercel.app/changelog",
      priority: 0.8,
    },
  ];
}
