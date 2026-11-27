"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Today" },
  { href: "/calibration", label: "Calibration" },
  { href: "/status", label: "Status" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <header className="border-b border-[var(--line)] bg-[var(--panel)]/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <Link href="/" className="font-mono text-sm font-medium tracking-tight">
          nba_alpha_prop
        </Link>
        <nav className="flex flex-wrap gap-4 text-sm">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={
                  active
                    ? "border-b-2 border-[var(--accent)] pb-0.5 font-medium text-[var(--foreground)]"
                    : "border-b-2 border-transparent pb-0.5 text-[var(--muted)] hover:text-[var(--foreground)]"
                }
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
