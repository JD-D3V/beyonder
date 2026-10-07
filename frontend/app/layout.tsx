import "./globals.css";
import "./reader.css";
import "./terms.css";
import type { Metadata } from "next";
import Nav from "../components/Nav";
import { fontVariables } from "../lib/fonts";

export const metadata: Metadata = {
  title: "Beyonder",
  description: "Multi-agent Chinese web-novel translation and Q&A",
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
