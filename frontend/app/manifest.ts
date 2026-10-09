import type { MetadataRoute } from "next";

// Static export: emitted once at build time, so the base path (GitHub Pages
// serves under /<repo>) is baked in here rather than in a static file.
export const dynamic = "force-static";

const base = process.env.NEXT_PUBLIC_BASE_PATH || "";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Beyonder",
    short_name: "Beyonder",
    description: "Multi-agent Chinese web-novel translation and Q&A",
    start_url: `${base}/`,
    scope: `${base}/`,
    display: "standalone",
    background_color: "#0d1117", // --bg (dark)
    theme_color: "#161b22", // --panel (dark), matches the top bar
    icons: [
      { src: `${base}/icons/icon-192.png`, sizes: "192x192", type: "image/png", purpose: "any" },
      { src: `${base}/icons/icon-512.png`, sizes: "512x512", type: "image/png", purpose: "any" },    ],
  };
}
