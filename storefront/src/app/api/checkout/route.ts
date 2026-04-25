import { NextResponse } from "next/server";

type Body = {
  variantId: string;
  productId: string;
  quantity?: number;
  custom?: Record<string, string>;
};

export async function POST(req: Request) {
  const body = (await req.json()) as Body;
  if (!body.variantId) {
    return NextResponse.json({ error: "variantId required" }, { status: 400 });
  }

  const apiKey = process.env.LEMONSQUEEZY_API_KEY;
  const storeId = process.env.LEMONSQUEEZY_STORE_ID;

  // Dev fallback: when env not configured, return a placeholder URL so the
  // overlay flow can be exercised end-to-end without secrets.
  if (!apiKey || !storeId) {
    return NextResponse.json({ dev: true });
  }

  const res = await fetch("https://api.lemonsqueezy.com/v1/checkouts", {
    method: "POST",
    headers: {
      Accept: "application/vnd.api+json",
      "Content-Type": "application/vnd.api+json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      data: {
        type: "checkouts",
        attributes: {
          checkout_options: { embed: true, media: false, logo: true },
          checkout_data: {
            custom: body.custom ?? {},
          },
          product_options: {
            enabled_variants: [Number(body.variantId)],
          },
        },
        relationships: {
          store: { data: { type: "stores", id: String(storeId) } },
          variant: { data: { type: "variants", id: String(body.variantId) } },
        },
      },
    }),
  });

  if (!res.ok) {
    return NextResponse.json(
      { error: "Failed to create checkout" },
      { status: 502 }
    );
  }
  const json = (await res.json()) as {
    data: { attributes: { url: string } };
  };
  return NextResponse.json({ url: json.data.attributes.url });
}
