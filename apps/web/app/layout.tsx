import "@fontsource-variable/dm-sans";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AFTERIMAGE — Evidence-Gated Trading Agent",
  description: "A verifiable evidence desk for autonomous paper options execution.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
