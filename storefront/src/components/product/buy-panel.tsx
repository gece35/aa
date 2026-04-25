"use client";

import { useState, useTransition } from "react";
import { ShoppingBag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn, formatPrice } from "@/lib/utils";
import { openLemonCheckout } from "@/lib/lemonsqueezy";
import type { Product } from "@/data/products";
import type { Dictionary } from "@/lib/dictionaries";

type Props = { product: Product; dict: Dictionary };

export function BuyPanel({ product, dict }: Props) {
  const [size, setSize] = useState(product.sizes[0]);
  const [color, setColor] = useState(product.colors[0]);
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function buy() {
    setError(null);
    start(async () => {
      try {
        await openLemonCheckout({
          variantId: product.variantId,
          productId: product.productId,
          custom: { size, color: color.name },
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "Something went wrong");
      }
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          {product.name}
        </h1>
        <p className="mt-2 text-2xl text-foreground/80">
          {formatPrice(product.price, product.currency)}
        </p>
      </div>
      <p className="text-foreground/70 leading-relaxed">{product.description}</p>

      <div>
        <p className="mb-2 text-sm font-medium">
          {dict.product.color} · {color.name}
        </p>
        <div className="flex gap-2">
          {product.colors.map((c) => (
            <button
              key={c.name}
              aria-label={c.name}
              onClick={() => setColor(c)}
              className={cn(
                "h-9 w-9 rounded-full border-2 transition",
                color.name === c.name
                  ? "border-foreground"
                  : "border-foreground/15 hover:border-foreground/40"
              )}
              style={{ background: c.hex }}
            />
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">
          {dict.product.size} · {size}
        </p>
        <div className="flex flex-wrap gap-2">
          {product.sizes.map((s) => (
            <button
              key={s}
              onClick={() => setSize(s)}
              className={cn(
                "min-w-12 rounded-full border px-4 py-2 text-sm transition",
                size === s
                  ? "border-foreground bg-foreground text-background"
                  : "border-foreground/15 hover:border-foreground/40"
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <Button size="lg" onClick={buy} disabled={pending} className="w-full">
        <ShoppingBag className="h-4 w-4" />
        {pending ? dict.product.opening_checkout : dict.product.buy_now}
      </Button>
      {error && <p className="text-sm text-red-500">{error}</p>}
      <p className="text-xs text-foreground/50">{dict.product.trust}</p>
    </div>
  );
}
