"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import type { Locale } from "@/lib/dictionaries";

export function LanguageSwitcher({ lang }: { lang: Locale }) {
  const pathname = usePathname();

  function switchTo(target: Locale) {
    // Replace the first path segment (locale) with the target
    const segments = pathname.split("/");
    segments[1] = target;
    return segments.join("/") || "/";
  }

  return (
    <div className="flex items-center gap-1 rounded-full border border-foreground/10 p-0.5 text-xs font-medium">
      {(["en", "tr"] as Locale[]).map((l) => (
        <Link
          key={l}
          href={switchTo(l)}
          className={cn(
            "rounded-full px-2.5 py-1 transition",
            lang === l
              ? "bg-foreground text-background"
              : "text-foreground/60 hover:text-foreground"
          )}
        >
          {l.toUpperCase()}
        </Link>
      ))}
    </div>
  );
}
