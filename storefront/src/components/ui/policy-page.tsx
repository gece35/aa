import Link from "next/link";
import type { Locale } from "@/lib/dictionaries";

type Section = { heading: string; body: string[] };

type Props = {
  lang: Locale;
  backLabel: string;
  title: string;
  effective: string;
  sections: Section[];
};

export function PolicyPage({ lang, backLabel, title, effective, sections }: Props) {
  return (
    <div className="mx-auto max-w-3xl px-6 py-16 sm:px-8 sm:py-24">
      <Link
        href={`/${lang}`}
        className="mb-10 inline-block text-sm text-foreground/50 hover:text-foreground transition"
      >
        {backLabel}
      </Link>
      <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
      <p className="mt-2 text-sm text-foreground/50">{effective}</p>
      <div className="mt-12 space-y-10">
        {sections.map((section) => (
          <section key={section.heading}>
            <h2 className="text-base font-semibold">{section.heading}</h2>
            <div className="mt-3 space-y-3">
              {section.body.map((paragraph, i) => (
                <p key={i} className="text-sm leading-relaxed text-foreground/70">
                  {paragraph}
                </p>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
