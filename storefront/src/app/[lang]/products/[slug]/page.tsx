import { notFound } from "next/navigation";
import { getDictionary, hasLocale } from "@/lib/dictionaries";
import { PRODUCTS, getProduct } from "@/data/products";
import { Header } from "@/components/sections/header";
import { Footer } from "@/components/sections/footer";
import { Gallery } from "@/components/product/gallery";
import { BuyPanel } from "@/components/product/buy-panel";

export function generateStaticParams() {
  return PRODUCTS.flatMap((p) => [
    { lang: "en", slug: p.slug },
    { lang: "tr", slug: p.slug },
  ]);
}

export async function generateMetadata(
  props: PageProps<"/[lang]/products/[slug]">
) {
  const { slug } = await props.params;
  const product = getProduct(slug);
  if (!product) return {};
  return {
    title: `${product.name} · Atelier.AI`,
    description: product.description,
    openGraph: { images: [product.image] },
  };
}

export default async function ProductPage(
  props: PageProps<"/[lang]/products/[slug]">
) {
  const { lang, slug } = await props.params;
  if (!hasLocale(lang)) notFound();
  const product = getProduct(slug);
  if (!product) notFound();
  const dict = await getDictionary(lang);

  return (
    <>
      <Header lang={lang} dict={dict} />
      <main className="flex-1">
        <div className="mx-auto grid max-w-6xl gap-10 px-6 py-10 sm:px-8 sm:py-14 lg:grid-cols-2">
          <Gallery images={product.gallery} alt={product.name} />
          <BuyPanel product={product} dict={dict} />
        </div>
      </main>
      <Footer lang={lang} dict={dict} />
    </>
  );
}
