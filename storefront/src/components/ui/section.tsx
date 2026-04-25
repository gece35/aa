import { cn } from "@/lib/utils";

export function Section({
  className,
  children,
  id,
}: {
  className?: string;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className={cn("w-full px-6 sm:px-8", className)}>
      <div className="mx-auto max-w-6xl">{children}</div>
    </section>
  );
}
