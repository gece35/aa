"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Dictionary, Locale } from "@/lib/dictionaries";

type Props = { dict: Dictionary; lang: Locale };

export function Hero({ dict, lang }: Props) {
  return (
    <section className="relative overflow-hidden">
      <div className="mx-auto flex max-w-6xl flex-col items-start gap-8 px-6 py-24 sm:px-8 sm:py-32 lg:py-40">
        <motion.span
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="rounded-full border border-foreground/10 px-3 py-1 text-xs font-medium text-foreground/70"
        >
          {dict.hero.badge}
        </motion.span>
        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.05 }}
          className="max-w-3xl text-5xl font-semibold leading-[1.05] tracking-tight sm:text-6xl lg:text-7xl"
        >
          {dict.hero.heading}
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="max-w-xl text-base text-foreground/70 sm:text-lg"
        >
          {dict.hero.subtext}
        </motion.p>
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15 }}
          className="flex flex-wrap gap-3"
        >
          <Link href={`/${lang}/#products`}>
            <Button size="lg">
              {dict.hero.cta_primary}
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
          <Link href={`/${lang}/#why`}>
            <Button size="lg" variant="outline">
              {dict.hero.cta_secondary}
            </Button>
          </Link>
        </motion.div>
      </div>
    </section>
  );
}
