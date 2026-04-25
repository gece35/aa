import { ShieldCheck, Truck, Sparkles, Globe2 } from "lucide-react";
import { Section } from "@/components/ui/section";
import type { Dictionary } from "@/lib/dictionaries";

const ICONS = [Sparkles, Truck, ShieldCheck, Globe2];

export function WhyUs({ dict }: { dict: Dictionary }) {
  return (
    <Section id="why" className="py-16 sm:py-24">
      <div className="mb-10 max-w-2xl">
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          {dict.why.heading}
        </h2>
        <p className="mt-3 text-foreground/70">{dict.why.subtext}</p>
      </div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {dict.why.features.map((feature, i) => {
          const Icon = ICONS[i];
          return (
            <div
              key={feature.title}
              className="rounded-2xl border border-foreground/10 p-6"
            >
              <Icon className="h-6 w-6 text-foreground" />
              <h3 className="mt-4 text-base font-medium">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-foreground/65">
                {feature.text}
              </p>
            </div>
          );
        })}
      </div>
    </Section>
  );
}
