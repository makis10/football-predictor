import type { MetadataRoute } from "next";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://aitipster.net";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const routes: { path: string; priority: number; freq: "daily" | "weekly" }[] = [
    { path: "",                            priority: 1.0, freq: "daily" },
    { path: "/stats",                      priority: 0.8, freq: "daily" },
    { path: "/recent",                     priority: 0.7, freq: "daily" },
    // /national is intentionally absent: it 307s to / since the 2026 World Cup
    // ended, and a sitemap that advertises redirects gets the whole file
    // discounted. Re-add it when the next tournament goes live.
    { path: "/contact",                    priority: 0.3, freq: "weekly" },
  ];
  return routes.map((r) => ({
    url: `${SITE_URL}${r.path}`,
    lastModified: now,
    changeFrequency: r.freq,
    priority: r.priority,
  }));
}
