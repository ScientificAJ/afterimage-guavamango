import "@fontsource-variable/dm-sans";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource/barlow-condensed/400.css";
import "@fontsource/barlow-condensed/500.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AFTERIMAGE / GuavaMango — Autonomous Trading Flight Deck",
  description: "A proof-first autonomous paper-trading agent on Alpaca.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
