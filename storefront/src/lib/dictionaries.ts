import "server-only";

const dictionaries = {
  en: () =>
    import("@/dictionaries/en.json").then((m) => m.default),
  tr: () =>
    import("@/dictionaries/tr.json").then((m) => m.default),
};

export type Locale = keyof typeof dictionaries;
export type Dictionary = Awaited<ReturnType<typeof getDictionary>>;

export const LOCALES: Locale[] = ["en", "tr"];
export const DEFAULT_LOCALE: Locale = "en";

export function hasLocale(value: string): value is Locale {
  return value in dictionaries;
}

export async function getDictionary(locale: Locale) {
  return dictionaries[locale]();
}
