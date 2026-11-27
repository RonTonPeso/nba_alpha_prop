"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorState, LoadingState } from "../../components/States";
import { fetchStatus } from "../../lib/api";

export default function StatusPage() {
  const query = useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Status</h1>
        <p className="mt-1 max-w-xl text-sm text-[var(--muted)]">
          Ingestion freshness and registered scheduler jobs. Jobs stay idle
          unless SCHEDULER_ENABLED is true.
        </p>
      </div>

      {query.isLoading ? <LoadingState /> : null}
      {query.isError ? (
        <ErrorState
          message={
            query.error instanceof Error ? query.error.message : "Failed to load"
          }
        />
      ) : null}

      {query.data ? (
        <>
          <section className="border border-[var(--line)] bg-[var(--panel)] p-4">
            <h2 className="text-lg font-medium">Scheduler</h2>
            <p className="mt-2 text-sm">
              Enabled:{" "}
              <span className="font-mono font-medium">
                {query.data.scheduler_enabled ? "true" : "false"}
              </span>
            </p>
            <p className="mt-1 font-mono text-xs text-[var(--muted)]">
              API {query.data.api_version}
            </p>
            <ul className="mt-3 flex flex-wrap gap-2">
              {query.data.job_ids.map((id) => (
                <li
                  key={id}
                  className="border border-[var(--line)] bg-[var(--accent-soft)] px-2 py-1 font-mono text-xs text-[var(--foreground)]"
                >
                  {id}
                </li>
              ))}
            </ul>
          </section>

          <section className="border border-[var(--line)] bg-[var(--panel)] p-4">
            <h2 className="text-lg font-medium">Freshness</h2>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-[var(--muted)]">
                  <tr>
                    <th className="py-2 pr-3">Table</th>
                    <th className="py-2 pr-3">Rows</th>
                    <th className="py-2 pr-3">Max available_at</th>
                    <th className="py-2">Max ingested_at</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.freshness.map((row) => (
                    <tr
                      key={row.table}
                      className="border-t border-[var(--line)]"
                    >
                      <td className="py-2 pr-3 font-mono text-xs">{row.table}</td>
                      <td className="py-2 pr-3 tabular">{row.row_count ?? "—"}</td>
                      <td className="py-2 pr-3 font-mono text-xs">
                        {row.max_available_at
                          ? new Date(row.max_available_at).toLocaleString()
                          : "—"}
                      </td>
                      <td className="py-2 font-mono text-xs">
                        {row.max_ingested_at
                          ? new Date(row.max_ingested_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
