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
        <Link href="/" className="text-sm text-[var(--accent)] hover:underline">
          ← Today
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {detailQuery.data?.player_name ?? `Player ${playerId}`}
        </h1>
        <p className="mt-1 max-w-xl text-sm text-[var(--muted)]">
          Density from the stored mean and std. Market line marked when a quote
          exists.
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
          <section className="border border-[var(--line)] bg-[var(--panel)] p-4">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-lg font-medium capitalize">
                {detailQuery.data.prop_type} forecast
              </h2>
              <p className="font-mono text-xs text-[var(--muted)]">
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
                    <dt className="text-[var(--muted)]">Mean</dt>
                    <dd className="font-medium tabular">{detailQuery.data.mean.toFixed(2)}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--muted)]">Std</dt>
                    <dd className="font-medium tabular">
                      {detailQuery.data.std?.toFixed(2) ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[var(--muted)]">Model P</dt>
                    <dd className="font-medium tabular">{formatPct(detailQuery.data.model_p)}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--muted)]">Gap vs mid</dt>
                    <dd className="font-medium tabular">{formatGap(detailQuery.data.gap)}</dd>
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
            <div className="border border-[var(--line)] bg-[var(--panel)] p-4">
              <h2 className="text-lg font-medium">Top SHAP</h2>
              {detailQuery.data.shap_top5.length === 0 ? (
                <p className="mt-3 text-sm text-[var(--muted)]">
                  No SHAP payload on this row (common for baseline and posterior).
                </p>
              ) : (
                <ul className="mt-3 space-y-2 text-sm">
                  {detailQuery.data.shap_top5.map((item) => (
                    <li
                      key={item.feature}
                      className="flex justify-between gap-3 border-b border-[var(--line)] py-1"
                    >
                      <span className="font-mono text-xs">{item.feature}</span>
                      <span className="tabular">{item.shap.toFixed(3)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="border border-[var(--line)] bg-[var(--panel)] p-4">
              <h2 className="text-lg font-medium">Recent injury signals</h2>
              {detailQuery.data.injuries.length === 0 ? (
                <p className="mt-3 text-sm text-[var(--muted)]">
                  No injury signals for this player at the slate clock.
                </p>
              ) : (
                <ul className="mt-3 space-y-3 text-sm">
                  {detailQuery.data.injuries.map((inj) => (
                    <li key={inj.injury_signal_id} className="border-b border-[var(--line)] pb-2">
                      <p className="font-medium capitalize">
                        {inj.claim_type}
                        {inj.severity ? ` · ${inj.severity}` : ""}
                      </p>
                      <p className="font-mono text-xs text-[var(--muted)]">
                        {inj.source} · conf {inj.confidence.toFixed(2)} ·{" "}
                        {new Date(inj.event_time).toLocaleString()}
                      </p>
                      <p className="mt-1 text-[var(--foreground)]">{inj.raw_text}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          {detailQuery.data.comparisons.length > 0 ? (
            <section className="border border-[var(--line)] bg-[var(--panel)] p-4">
              <h2 className="text-lg font-medium">Comparisons on this slate</h2>
              <ul className="mt-3 divide-y divide-[var(--line)] text-sm">
                {detailQuery.data.comparisons.map((row) => (
                  <li
                    key={`${row.prop_type}-${row.line}`}
                    className="flex flex-wrap items-center justify-between gap-2 py-2"
                  >
                    <span className="capitalize">
                      {row.prop_type} {row.line}
                    </span>
                    <span className="tabular">
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
