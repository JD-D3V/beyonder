import "./globals.css";
import "./reader.css";
import "./terms.css";
import type { Metadata, Viewport } from "next";
import Nav from "../components/Nav";
import { fontVariables } from "../lib/fonts";

const BASE = process.env.NEXT_PUBLIC_BASE_PATH || "";

export const metadata: Metadata = {
  title: "Beyonder",
  description: "Multi-agent Chinese web-novel translation and Q&A",
  // The manifest link is emitted by app/manifest.ts.
  icons: {
    icon: [{ url: `${BASE}/icons/icon-192.png`, sizes: "192x192", type: "image/png" }],
    apple: [{ url: `${BASE}/icons/apple-touch-icon.png`, sizes: "180x180" }],
  },
  appleWebApp: { capable: true, title: "Beyonder", statusBarStyle: "black-translucent" },
};

// <meta name="theme-color">, matching the --panel token of each theme.
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#161b22" },
  ],
};

// Constant string, no user data. Applies the stored site theme before first paint.
const THEME_SCRIPT =
  'try{var t=localStorage.getItem("beyonder.siteTheme");' +
  'if(t!=="light"&&t!=="dark")t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";' +
  'document.documentElement.dataset.theme=t}catch(e){}';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className={fontVariables}>
        <Nav />
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
