"use client";

import { useQuery } from "@tanstack/react-query";

import { CalibrationChart } from "../../components/CalibrationChart";
import { EmptyState, ErrorState, LoadingState } from "../../components/States";
import { fetchCalibration } from "../../lib/api";

export default function CalibrationPage() {
  const query = useQuery({
    queryKey: ["calibration"],
    queryFn: fetchCalibration,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Calibration</h1>
        <p className="mt-1 max-w-xl text-sm text-[var(--muted)]">
          Precomputed reliability from docs/results. This page does not re-run
          models.
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
            <h2 className="text-lg font-medium">{query.data.title}</h2>
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-[var(--muted)]">Brier</dt>
                <dd className="font-medium tabular">
                  {query.data.brier?.toFixed(6) ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Calibration error</dt>
                <dd className="font-medium tabular">
                  {query.data.calibration_error?.toFixed(6) ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Contracts</dt>
                <dd className="font-medium tabular">{query.data.n_contracts ?? "—"}</dd>
              </div>
            </dl>
            {query.data.disagreement_note ? (
              <p className="mt-3 text-sm text-[var(--muted)]">
                {query.data.disagreement_note}
              </p>
            ) : null}
            <div className="mt-4">
              {query.data.bins.length ? (
                <CalibrationChart bins={query.data.bins} />
              ) : (
                <EmptyState title="No bins parsed from the M4 report" />
              )}
            </div>
          </section>

          <section className="border border-[var(--line)] bg-[var(--panel)] p-4">
            <h2 className="text-lg font-medium">Model Brier by report</h2>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-[var(--muted)]">
                  <tr>
                    <th className="py-2 pr-3">Prop</th>
                    <th className="py-2 pr-3">Version</th>
                    <th className="py-2 pr-3">Brier</th>
                    <th className="py-2 pr-3">Compare</th>
                    <th className="py-2">N</th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.props.map((row) => (
                    <tr
                      key={`${row.model_version}-${row.prop_type}-${row.source}`}
                      className="border-t border-[var(--line)]"
                    >
                      <td className="py-2 pr-3 capitalize">{row.prop_type}</td>
                      <td className="py-2 pr-3 font-mono text-xs">
                        {row.model_version}
                      </td>
                      <td className="py-2 pr-3 tabular">
                        {row.brier?.toFixed(6) ?? "—"}
                      </td>
                      <td className="py-2 pr-3 tabular">
                        {row.residual_brier?.toFixed(6) ?? "—"}
                      </td>
                      <td className="py-2 tabular">{row.n_contracts ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="mt-4 list-disc space-y-1 pl-5 font-mono text-xs text-[var(--muted)]">
              {query.data.source_files.map((file) => (
                <li key={file}>{file}</li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </div>
  );
}
