"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "../components/States";
import {
  fetchComparisonDates,
  fetchComparisonsToday,
  formatGap,
  formatPct,
} from "../lib/api";

export default function TodayPage() {
  const [date, setDate] = useState<string>("");
  const datesQuery = useQuery({
    queryKey: ["comparison-dates"],
    queryFn: fetchComparisonDates,
  });
  const comparisonsQuery = useQuery({
    queryKey: ["comparisons-today", date || "default"],
    queryFn: () => fetchComparisonsToday(date || undefined),
  });

  const availableDates = datesQuery.data?.dates ?? [];
  const rows = comparisonsQuery.data?.rows ?? [];
  const sorted = useMemo(
    () =>
      [...rows].sort((a, b) => {
        const ag = a.gap === null ? -1 : Math.abs(a.gap);
        const bg = b.gap === null ? -1 : Math.abs(b.gap);
        return bg - ag;
      }),
    [rows],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Today</h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Model probability versus Kalshi yes mid. Gap is model minus mid, in
            probability points. Not an edge or EV claim.
          </p>
        </div>
        <label className="text-sm text-zinc-600 dark:text-zinc-400">
          Slate date
          <select
            className="mt-1 block w-full min-w-44 rounded-md border border-zinc-300 bg-white px-3 py-2 text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            value={date || comparisonsQuery.data?.date || ""}
            onChange={(e) => setDate(e.target.value)}
          >
            {!availableDates.length ? (
              <option value="">No dated slates</option>
            ) : (
              availableDates.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))
            )}
          </select>
        </label>
      </div>

      {comparisonsQuery.isLoading ? <LoadingState label="Loading comparisons…" /> : null}
      {comparisonsQuery.isError ? (
        <ErrorState
          message={
            comparisonsQuery.error instanceof Error
              ? comparisonsQuery.error.message
              : "Failed to load comparisons"
          }
        />
      ) : null}
      {comparisonsQuery.isSuccess && sorted.length === 0 ? (
        <EmptyState
          title="No comparisons for this date"
          detail="Need stored predictions joined to Kalshi markets. Pick another slate date, or run daily predict and snapshots."
        />
      ) : null}

      {sorted.length > 0 ? (
        <>
          <p className="text-xs text-zinc-500">
            Showing {sorted.length} rows for {comparisonsQuery.data?.date}. As of{" "}
            {comparisonsQuery.data?.as_of}.
          </p>
          <div className="hidden overflow-x-auto rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 md:block">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-zinc-200 bg-zinc-100 text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950">
                <tr>
                  <th className="px-3 py-2 font-medium">Player</th>
                  <th className="px-3 py-2 font-medium">Prop</th>
                  <th className="px-3 py-2 font-medium">Line</th>
                  <th className="px-3 py-2 font-medium">Model P</th>
                  <th className="px-3 py-2 font-medium">Mid</th>
                  <th className="px-3 py-2 font-medium">Gap</th>
                  <th className="px-3 py-2 font-medium">Version</th>
                  <th className="px-3 py-2 font-medium">Flags</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row) => (
                  <tr
                    key={`${row.player_id}-${row.game_id}-${row.prop_type}-${row.line}`}
                    className="border-b border-zinc-100 dark:border-zinc-800"
                  >
                    <td className="px-3 py-2">
                      <Link
                        href={`/players/${row.player_id}?game_id=${row.game_id}&prop_type=${row.prop_type}`}
                        className="font-medium text-blue-700 hover:underline dark:text-blue-300"
                      >
                        {row.player_name}
                      </Link>
                    </td>
                    <td className="px-3 py-2 capitalize">{row.prop_type}</td>
                    <td className="px-3 py-2">{row.line}</td>
                    <td className="px-3 py-2">{formatPct(row.model_p)}</td>
                    <td className="px-3 py-2">{formatPct(row.market_mid)}</td>
                    <td className="px-3 py-2 font-medium">{formatGap(row.gap)}</td>
                    <td className="px-3 py-2 font-mono text-xs">{row.model_version}</td>
                    <td className="px-3 py-2 text-xs">
                      {row.low_confidence ? "low confidence" : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="space-y-3 md:hidden">
            {sorted.map((row) => (
              <Link
                key={`${row.player_id}-${row.game_id}-${row.prop_type}-${row.line}-card`}
                href={`/players/${row.player_id}?game_id=${row.game_id}&prop_type=${row.prop_type}`}
                className="block rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-medium">{row.player_name}</p>
                    <p className="text-sm capitalize text-zinc-500">
                      {row.prop_type} · {row.line}
                    </p>
                  </div>
                  <p className="text-sm font-semibold">{formatGap(row.gap)}</p>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                  <div>
                    <dt>Model P</dt>
                    <dd className="text-zinc-900 dark:text-zinc-100">
                      {formatPct(row.model_p)}
                    </dd>
                  </div>
                  <div>
                    <dt>Mid</dt>
                    <dd className="text-zinc-900 dark:text-zinc-100">
                      {formatPct(row.market_mid)}
                    </dd>
                  </div>
                  <div className="col-span-2 font-mono">{row.model_version}</div>
                </dl>
              </Link>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
