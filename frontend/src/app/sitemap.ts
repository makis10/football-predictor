import type { MetadataRoute } from "next";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://aitipster.net";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const routes: { path: string; priority: number; freq: "daily" | "weekly" }[] = [
    { path: "",                            priority: 1.0, freq: "daily" },
    { path: "/stats",                      priority: 0.8, freq: "daily" },
    { path: "/recent",                     priority: 0.7, freq: "daily" },
    { path: "/national",                   priority: 0.7, freq: "daily" },
    // The World Cup simulation route is gone (tournament over — it permanently
    // redirects to the review), so only the retrospective is advertised now.
    { path: "/national/world-cup/review",  priority: 0.7, freq: "weekly" },
    { path: "/contact",                    priority: 0.3, freq: "weekly" },
  ];
  return routes.map((r) => ({
    url: `${SITE_URL}${r.path}`,
    lastModified: now,
    changeFrequency: r.freq,
    priority: r.priority,
  }));
}
