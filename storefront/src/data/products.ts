export type Product = {
  slug: string;
  name: string;
  description: string;
  price: number;
  currency: string;
  image: string;
  gallery: string[];
  variantId: string;
  productId: string;
  sizes: string[];
  colors: { name: string; hex: string }[];
  badge?: string;
};

export const PRODUCTS: Product[] = [
  {
    slug: "abstract-dream-tee",
    name: "Abstract Dream Tee",
    description:
      "AI-generated geometric pattern, premium 240gsm combed cotton, archival pigment print.",
    price: 39,
    currency: "USD",
    image:
      "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=900&q=80",
    gallery: [
      "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=1200&q=80",
      "https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?auto=format&fit=crop&w=1200&q=80",
    ],
    variantId: "VAR_001",
    productId: "PRD_001",
    sizes: ["S", "M", "L", "XL"],
    colors: [
      { name: "Black", hex: "#0a0a0a" },
      { name: "Bone", hex: "#efe9dd" },
    ],
    badge: "New",
  },
  {
    slug: "neon-bloom-hoodie",
    name: "Neon Bloom Hoodie",
    description:
      "Heavyweight 400gsm fleece with vivid AI-art print. Cut for relaxed, all-day wear.",
    price: 79,
    currency: "USD",
    image:
      "https://images.unsplash.com/photo-1556821840-3a63f95609a7?auto=format&fit=crop&w=900&q=80",
    gallery: [
      "https://images.unsplash.com/photo-1556821840-3a63f95609a7?auto=format&fit=crop&w=1200&q=80",
    ],
    variantId: "VAR_002",
    productId: "PRD_002",
    sizes: ["M", "L", "XL"],
    colors: [
      { name: "Charcoal", hex: "#222" },
      { name: "Sand", hex: "#d6c7ad" },
    ],
    badge: "Bestseller",
  },
  {
    slug: "midnight-poster",
    name: "Midnight Poster A2",
    description:
      "Giclée print on 250gsm matte fine art paper. Limited run, signed digital edition.",
    price: 29,
    currency: "USD",
    image:
      "https://images.unsplash.com/photo-1513542789411-b6a5d4f31634?auto=format&fit=crop&w=900&q=80",
    gallery: [
      "https://images.unsplash.com/photo-1513542789411-b6a5d4f31634?auto=format&fit=crop&w=1200&q=80",
    ],
    variantId: "VAR_003",
    productId: "PRD_003",
    sizes: ["A3", "A2", "A1"],
    colors: [{ name: "Black Frame", hex: "#0a0a0a" }],
  },
  {
    slug: "solar-flare-cap",
    name: "Solar Flare Cap",
    description:
      "Embroidered AI-art motif on a structured 6-panel cap. Adjustable strap, premium twill.",
    price: 28,
    currency: "USD",
    image:
      "https://images.unsplash.com/photo-1588850561407-ed78c282e89b?auto=format&fit=crop&w=900&q=80",
    gallery: [
      "https://images.unsplash.com/photo-1588850561407-ed78c282e89b?auto=format&fit=crop&w=1200&q=80",
    ],
    variantId: "VAR_004",
    productId: "PRD_004",
    sizes: ["One Size"],
    colors: [
      { name: "Black", hex: "#0a0a0a" },
      { name: "Cream", hex: "#f3ecdc" },
    ],
  },
];

export function getProduct(slug: string) {
  return PRODUCTS.find((p) => p.slug === slug);
}
