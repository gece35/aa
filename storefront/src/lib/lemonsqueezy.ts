export type CheckoutPayload = {
  variantId: string;
  productId: string;
  quantity?: number;
  custom?: Record<string, string>;
};

export type CheckoutResponse = {
  url?: string;
  dev?: boolean;
};

declare global {
  interface Window {
    LemonSqueezy?: {
      Setup: (opts: { eventHandler?: (e: unknown) => void }) => void;
      Url: { Open: (url: string) => void; Close: () => void };
    };
    createLemonSqueezy?: () => void;
  }
}

let scriptLoaded: Promise<void> | null = null;

function loadOverlayScript(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.LemonSqueezy) return Promise.resolve();
  if (scriptLoaded) return scriptLoaded;
  scriptLoaded = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://app.lemonsqueezy.com/js/lemon.js";
    s.defer = true;
    s.onload = () => {
      window.createLemonSqueezy?.();
      window.LemonSqueezy?.Setup({});
      resolve();
    };
    s.onerror = () => reject(new Error("Failed to load LemonSqueezy script"));
    document.head.appendChild(s);
  });
  return scriptLoaded;
}

export async function openLemonCheckout(payload: CheckoutPayload) {
  const res = await fetch("/api/checkout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Checkout creation failed");
  const data = (await res.json()) as CheckoutResponse;
  if (data.dev) {
    throw new Error(
      "Ödeme sistemi henüz yapılandırılmadı. Gerçek bir sipariş için LEMONSQUEEZY_API_KEY ve LEMONSQUEEZY_STORE_ID ortam değişkenlerini tanımlayın."
    );
  }
  await loadOverlayScript();
  if (typeof window !== "undefined" && window.LemonSqueezy && data.url) {
    window.LemonSqueezy.Url.Open(data.url);
  } else if (data.url) {
    window.location.href = data.url;
  }
}
