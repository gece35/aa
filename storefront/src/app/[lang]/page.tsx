import { notFound } from "next/navigation";
import { getDictionary, hasLocale } from "@/lib/dictionaries";
import { Header } from "@/components/sections/header";
import { Hero } from "@/components/sections/hero";
import { Featured } from "@/components/sections/featured";
import { WhyUs } from "@/components/sections/why-us";
import { Footer } from "@/components/sections/footer";

export default async function HomePage(props: PageProps<"/[lang]">) {
  const { lang } = await props.params;
  if (!hasLocale(lang)) notFound();
  const dict = await getDictionary(lang);

  return (
    <>
      <Header lang={lang} dict={dict} />
      <main className="flex-1">
        <Hero lang={lang} dict={dict} />
        <Featured lang={lang} dict={dict} />
        <WhyUs dict={dict} />
      </main>
      <Footer lang={lang} dict={dict} />
    </>
  );
}
