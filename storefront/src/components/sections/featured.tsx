import Link from "next/link";
import Image from "next/image";
import { Section } from "@/components/ui/section";
import { PRODUCTS } from "@/data/products";
import { formatPrice } from "@/lib/utils";
import type { Dictionary, Locale } from "@/lib/dictionaries";

type Props = { dict: Dictionary; lang: Locale };

export function Featured({ dict, lang }: Props) {
  return (
    <Section id="products" className="py-16 sm:py-24">
      <div className="mb-10 flex items-end justify-between gap-4">
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          {dict.featured.heading}
        </h2>
        <p className="hidden text-sm text-foreground/60 sm:block">
          {dict.featured.subheading}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-10 sm:gap-x-6 lg:grid-cols-4">
        {PRODUCTS.map((p) => (
          <Link
            key={p.slug}
            href={`/${lang}/products/${p.slug}`}
            prefetch
            className="group flex flex-col gap-3"
          >
            <div className="relative aspect-[4/5] overflow-hidden rounded-2xl bg-foreground/5">
              <Image
                src={p.image}
                alt={p.name}
                fill
                sizes="(min-width: 1024px) 25vw, (min-width: 640px) 33vw, 50vw"
                className="object-cover transition-transform duration-500 group-hover:scale-105"
              />
              {p.badge && (
                <span className="absolute left-3 top-3 rounded-full bg-background/90 px-3 py-1 text-xs font-medium text-foreground backdrop-blur">
                  {p.badge}
                </span>
              )}
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-sm font-medium tracking-tight">{p.name}</h3>
              <span className="text-sm text-foreground/70">
                {formatPrice(p.price, p.currency)}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </Section>
  );
}
