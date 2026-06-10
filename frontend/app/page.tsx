import { Feed } from "@/components/feed";

export default function HomePage() {
  return (
    <Feed
      header={
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Your saves</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Everything you saved or DMed, automatically organized.
          </p>
        </div>
      }
    />
  );
}
