import { notFound } from "next/navigation";
import { getDictionary, hasLocale } from "@/lib/dictionaries";
import { Header } from "@/components/sections/header";
import { Footer } from "@/components/sections/footer";
import { PolicyPage } from "@/components/ui/policy-page";

export default async function TermsPage(props: PageProps<"/[lang]/terms">) {
  const { lang } = await props.params;
  if (!hasLocale(lang)) notFound();
  const dict = await getDictionary(lang);
  const policy = dict.policies.terms;

  return (
    <>
      <Header lang={lang} dict={dict} />
      <main className="flex-1">
        <PolicyPage
          lang={lang}
          backLabel={dict.policies.back}
          title={policy.title}
          effective={policy.effective}
          sections={policy.sections}
        />
      </main>
      <Footer lang={lang} dict={dict} />
    </>
  );
}
