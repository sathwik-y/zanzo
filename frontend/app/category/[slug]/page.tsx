import { notFound } from "next/navigation";
import { Feed } from "@/components/feed";
import { CATEGORY_META, SLUG_TO_CATEGORY } from "@/lib/api";

export default async function CategoryPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const category = SLUG_TO_CATEGORY[slug];
  if (!category) notFound();
  const meta = CATEGORY_META[category];

  return (
    <Feed
      fixedCategory={category}
      header={
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">{meta.label}</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Saved items classified as {meta.label.toLowerCase()}.
          </p>
        </div>
      }
    />
  );
}
