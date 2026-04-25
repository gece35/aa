import Image from "next/image";

export function Gallery({
  images,
  alt,
}: {
  images: string[];
  alt: string;
}) {
  const [main, ...rest] = images;
  return (
    <div className="flex flex-col gap-3">
      <div className="relative aspect-[4/5] overflow-hidden rounded-3xl bg-foreground/5">
        <Image
          src={main}
          alt={alt}
          fill
          priority
          fetchPriority="high"
          sizes="(min-width: 1024px) 50vw, 100vw"
          className="object-cover"
        />
      </div>
      {rest.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          {rest.map((src, i) => (
            <div
              key={src}
              className="relative aspect-square overflow-hidden rounded-xl bg-foreground/5"
            >
              <Image
                src={src}
                alt={`${alt} ${i + 2}`}
                fill
                sizes="(min-width: 1024px) 16vw, 33vw"
                className="object-cover"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
