/** @type {import('next').NextConfig} */

// GitHub Pages serves a project site under /<repo>, so every asset and link
// needs that prefix. Set NEXT_PUBLIC_BASE_PATH=/beyonder for Pages; leave it
// empty for Cloudflare Pages, Netlify, or local dev, which serve from root.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  // Static export — no Node runtime in prod.
  output: "export",
  reactStrictMode: true,
  poweredByHeader: false,
  // Trailing slash makes static hosting paths simpler.
  trailingSlash: true,
  basePath,
  assetPrefix: basePath || undefined,
  images: {
    unoptimized: true,
  },
  // Same-origin not required when backend is on :8000 — we proxy from client.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    NEXT_PUBLIC_BASE_PATH: basePath,
  },
};

export default nextConfig;
