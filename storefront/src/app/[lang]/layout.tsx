import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { LOCALES, hasLocale } from "@/lib/dictionaries";

export function generateStaticParams() {
  return LOCALES.map((lang) => ({ lang }));
}

export const metadata: Metadata = {
  title: "Atelier.AI — AI-crafted, made-to-order",
  description:
    "Premium print-on-demand apparel and prints. AI-generated art, archival-grade finish, shipped worldwide.",
};

export default async function LangLayout({
  children,
  params,
}: LayoutProps<"/[lang]">) {
  const { lang } = await params;
  if (!hasLocale(lang)) notFound();
  return <>{children}</>;
}
