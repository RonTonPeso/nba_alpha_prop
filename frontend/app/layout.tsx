import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "../components/Nav";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "nba_alpha_prop",
  description: "NBA player prop forecasting and market comparison",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-50">
        <Providers>
          <Nav />
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
