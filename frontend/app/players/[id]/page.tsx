"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { DensityChart } from "../../../components/DensityChart";
import { EmptyState, ErrorState, LoadingState } from "../../../components/States";
import { fetchPlayerDetail, formatGap, formatPct } from "../../../lib/api";

export default function PlayerDetailPage() {
  return (
    <Suspense fallback={<LoadingState label="Loading player…" />}>
      <PlayerDetailInner />
    </Suspense>
  );
}

function PlayerDetailInner() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const playerId = Number(params.id);
  const gameId = search.get("game_id") ?? undefined;
  const propType = search.get("prop_type") ?? "points";

  const detailQuery = useQuery({
    queryKey: ["player-detail", playerId, gameId, propType],
    queryFn: () =>
      fetchPlayerDetail(playerId, { game_id: gameId, prop_type: propType }),
    enabled: Number.isFinite(playerId),
  });

  if (!Number.isFinite(playerId)) {
    return <ErrorState message="Invalid player id" />;
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/" className="text-sm text-blue-700 hover:underline dark:text-blue-300">
          ← Today
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {detailQuery.data?.player_name ?? `Player ${playerId}`}
        </h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Forecast density from the stored mean and std, with the market line
          marked when available. Not an edge view.
        </p>
      </div>

      {detailQuery.isLoading ? <LoadingState /> : null}
      {detailQuery.isError ? (
        <ErrorState
          message={
            detailQuery.error instanceof Error
              ? detailQuery.error.message
              : "Failed to load player"
          }
        />
      ) : null}

      {detailQuery.data ? (
        <>
          <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-lg font-medium capitalize">
                {detailQuery.data.prop_type} forecast
              </h2>
              <p className="font-mono text-xs text-zinc-500">
                {detailQuery.data.model_version ?? "no forecast"}
                {detailQuery.data.distribution
                  ? ` · ${detailQuery.data.distribution}`
                  : ""}
              </p>
            </div>
            {detailQuery.data.mean === null ? (
              <EmptyState title="No stored forecast for this player and prop" />
            ) : (
              <>
                <dl className="mb-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  <div>
                    <dt className="text-zinc-500">Mean</dt>
                    <dd className="font-medium">{detailQuery.data.mean.toFixed(2)}</dd>
                  </div>
                  <div>
                    <dt className="text-zinc-500">Std</dt>
                    <dd className="font-medium">
                      {detailQuery.data.std?.toFixed(2) ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-zinc-500">Model P</dt>
                    <dd className="font-medium">{formatPct(detailQuery.data.model_p)}</dd>
                  </div>
                  <div>
                    <dt className="text-zinc-500">Gap vs mid</dt>
                    <dd className="font-medium">{formatGap(detailQuery.data.gap)}</dd>
                  </div>
                </dl>
                <DensityChart
                  data={detailQuery.data.density}
                  marketLine={detailQuery.data.market_line}
                  mean={detailQuery.data.mean}
                />
              </>
            )}
          </section>

          <section className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-lg font-medium">Top SHAP</h2>
              {detailQuery.data.shap_top5.length === 0 ? (
                <p className="mt-3 text-sm text-zinc-500">
                  No SHAP payload on this row (common for baseline and posterior).
                </p>
              ) : (
                <ul className="mt-3 space-y-2 text-sm">
                  {detailQuery.data.shap_top5.map((item) => (
                    <li
                      key={item.feature}
                      className="flex justify-between gap-3 border-b border-zinc-100 py-1 dark:border-zinc-800"
                    >
                      <span className="font-mono text-xs">{item.feature}</span>
                      <span>{item.shap.toFixed(3)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-lg font-medium">Recent injury signals</h2>
              {detailQuery.data.injuries.length === 0 ? (
                <p className="mt-3 text-sm text-zinc-500">
                  No injury signals for this player at the slate clock.
                </p>
              ) : (
                <ul className="mt-3 space-y-3 text-sm">
                  {detailQuery.data.injuries.map((inj) => (
                    <li key={inj.injury_signal_id} className="border-b border-zinc-100 pb-2 dark:border-zinc-800">
                      <p className="font-medium capitalize">
                        {inj.claim_type}
                        {inj.severity ? ` · ${inj.severity}` : ""}
                      </p>
                      <p className="text-xs text-zinc-500">
                        {inj.source} · conf {inj.confidence.toFixed(2)} ·{" "}
                        {new Date(inj.event_time).toLocaleString()}
                      </p>
                      <p className="mt-1 text-zinc-700 dark:text-zinc-300">{inj.raw_text}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          {detailQuery.data.comparisons.length > 0 ? (
            <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-lg font-medium">Comparisons on this slate</h2>
              <ul className="mt-3 divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
                {detailQuery.data.comparisons.map((row) => (
                  <li
                    key={`${row.prop_type}-${row.line}`}
                    className="flex flex-wrap items-center justify-between gap-2 py-2"
                  >
                    <span className="capitalize">
                      {row.prop_type} {row.line}
                    </span>
                    <span>
                      {formatPct(row.model_p)} vs {formatPct(row.market_mid)} (
                      {formatGap(row.gap)})
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
