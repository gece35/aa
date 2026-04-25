import Link from "next/link";
import type { Dictionary, Locale } from "@/lib/dictionaries";

type Props = { lang: Locale; dict: Dictionary };

export function Footer({ lang, dict }: Props) {
  return (
    <footer className="mt-24 border-t border-foreground/10">
      <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 px-6 py-10 text-sm text-foreground/60 sm:flex-row sm:items-center sm:px-8">
        <span>© {new Date().getFullYear()} Atelier.AI</span>
        <div className="flex flex-wrap gap-6">
          <Link href={`/${lang}/privacy`} className="hover:text-foreground transition">
            {dict.footer.privacy}
          </Link>
          <Link href={`/${lang}/terms`} className="hover:text-foreground transition">
            {dict.footer.terms}
          </Link>
          <Link href={`/${lang}/shipping`} className="hover:text-foreground transition">
            {dict.footer.shipping}
          </Link>
          <a href="mailto:hello@atelier.ai" className="hover:text-foreground transition">
            {dict.footer.contact}
          </a>
        </div>
      </div>
    </footer>
  );
}
