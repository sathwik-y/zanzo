"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertCircle, CheckCircle2, Loader2, PlayCircle, Wallet } from "lucide-react";
import { api, CATEGORY_META, PollerStatus, Stats } from "@/lib/api";

export default function SettingsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [poller, setPoller] = useState<PollerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api<Stats>("stats"), api<PollerStatus>("poller/status")]);
      setStats(s);
      setPoller(p);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  async function resume() {
    setResuming(true);
    try {
      setPoller(await api<PollerStatus>("poller/resume", { method: "POST" }));
    } finally {
      setResuming(false);
    }
  }

  const challenge = poller?.status === "challenge_required";

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-1 text-sm text-zinc-400">Poller health, processing stats and AI spend.</p>

      {error && (
        <div className="mt-6 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          Backend unreachable: {error}
        </div>
      )}

      <section className="mt-8 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 font-medium">
            <Activity className="size-4 text-violet-400" /> Instagram poller
          </h2>
          {poller &&
            (challenge ? (
              <span className="flex items-center gap-1.5 text-sm text-amber-300">
                <AlertCircle className="size-4" /> needs attention
              </span>
            ) : poller.status === "running" ? (
              <span className="flex items-center gap-1.5 text-sm text-emerald-300">
                <CheckCircle2 className="size-4" /> running
              </span>
            ) : (
              <span className="text-sm text-zinc-400">{poller.status}</span>
            ))}
        </div>

        {challenge && (
          <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
            <p className="font-medium">Instagram is asking for manual verification.</p>
            <p className="mt-1 text-amber-200/80">
              Open Instagram on your phone or browser, log into the bot account, approve the
              login (&quot;It was me&quot;), then click resume.
            </p>
            <button
              onClick={resume}
              disabled={resuming}
              className="mt-3 flex items-center gap-2 rounded-lg bg-amber-500/20 px-3 py-1.5 text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
            >
              {resuming ? <Loader2 className="size-4 animate-spin" /> : <PlayCircle className="size-4" />}
              Resume poller
            </button>
          </div>
        )}

        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat label="Last run" value={poller?.last_run_at ? new Date(poller.last_run_at).toLocaleTimeString() : "—"} />
          <Stat label="New last run" value={poller?.last_new_items ?? "—"} />
          <Stat label="Queue depth" value={poller?.queue_depth ?? "—"} />
          <Stat label="Status" value={poller?.status ?? "—"} />
        </dl>
        {poller?.last_error && !challenge && (
          <p className="mt-3 text-xs text-red-300/80">last error: {poller.last_error}</p>
        )}
      </section>

      <section className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
        <h2 className="flex items-center gap-2 font-medium">
          <Wallet className="size-4 text-violet-400" /> AI spend
        </h2>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat label="This month" value={stats ? `$${stats.llm_cost_month_usd.toFixed(3)}` : "—"} />
          <Stat label="All time" value={stats ? `$${stats.llm_cost_total_usd.toFixed(3)}` : "—"} />
          <Stat label="Items total" value={stats?.total_items ?? "—"} />
          <Stat label="Last 7 days" value={stats?.items_last_7_days ?? "—"} />
        </dl>
      </section>

      <section className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
        <h2 className="font-medium">Library breakdown</h2>
        <div className="mt-4 space-y-2">
          {stats &&
            Object.entries(stats.by_category)
              .sort(([, a], [, b]) => b - a)
              .map(([cat, count]) => {
                const meta = CATEGORY_META[cat] ?? CATEGORY_META.OTHER;
                const pct = stats.total_items ? Math.round((count / stats.total_items) * 100) : 0;
                return (
                  <div key={cat} className="flex items-center gap-3 text-sm">
                    <span className="w-28 text-zinc-400">{meta.label}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-zinc-800">
                      <div className="h-full rounded-full bg-violet-500/70" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="w-8 text-right text-zinc-300">{count}</span>
                  </div>
                );
              })}
          {stats && stats.failed_count > 0 && (
            <p className="pt-2 text-xs text-red-300/80">
              {stats.failed_count} item{stats.failed_count === 1 ? "" : "s"} failed processing — see the Failed tab.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-zinc-800/50 px-3 py-2.5">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="mt-0.5 font-medium text-zinc-200">{value}</dd>
    </div>
  );
}
