// Reader fonts: downloaded at build time and self-hosted by next/font.
import { Atkinson_Hyperlegible, Lexend, Lora, Nunito, Roboto } from "next/font/google";

const nunito = Nunito({ subsets: ["latin"], display: "swap", variable: "--font-nunito" });
const roboto = Roboto({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "700"],
  variable: "--font-roboto",
});
const lora = Lora({ subsets: ["latin"], display: "swap", variable: "--font-lora" });
const lexend = Lexend({ subsets: ["latin"], display: "swap", variable: "--font-lexend" });
const atkinson = Atkinson_Hyperlegible({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "700"],
  variable: "--font-atkinson",
});

export const fontVariables: string = [
  nunito.variable,
  roboto.variable,
  lora.variable,
  lexend.variable,
  atkinson.variable,
].join(" ");
