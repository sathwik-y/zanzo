import { Feed } from "@/components/feed";

export default function FailedPage() {
  return (
    <Feed
      fixedStatus="failed"
      header={
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Failed items</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Items that hit an error during processing. Open one to retry it.
          </p>
        </div>
      }
    />
  );
}
