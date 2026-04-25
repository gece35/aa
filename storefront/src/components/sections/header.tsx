import Link from "next/link";
import { ShoppingBag } from "lucide-react";
import { LanguageSwitcher } from "@/components/ui/language-switcher";
import type { Dictionary, Locale } from "@/lib/dictionaries";

type Props = { lang: Locale; dict: Dictionary };

export function Header({ lang, dict }: Props) {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-foreground/5 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6 sm:px-8">
        <Link href={`/${lang}`} className="text-base font-semibold tracking-tight">
          ATELIER<span className="text-foreground/50">.AI</span>
        </Link>
        <nav className="hidden gap-8 text-sm text-foreground/70 sm:flex">
          <Link href={`/${lang}/#products`} className="hover:text-foreground">
            {dict.nav.shop}
          </Link>
          <Link href={`/${lang}/#why`} className="hover:text-foreground">
            {dict.nav.why}
          </Link>
        </nav>
        <div className="flex items-center gap-3">
          <LanguageSwitcher lang={lang} />
          <button
            aria-label="Cart"
            className="rounded-full p-2 hover:bg-foreground/5"
          >
            <ShoppingBag className="h-5 w-5" />
          </button>
        </div>
      </div>
    </header>
  );
}
