export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="border border-[var(--line)] bg-[var(--panel)] px-4 py-10 text-center text-sm text-[var(--muted)]">
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  detail,
}: {
  title: string;
  detail?: string;
}) {
  return (
    <div className="border border-[var(--line)] bg-[var(--panel)] px-4 py-10 text-center">
      <p className="font-medium text-[var(--foreground)]">{title}</p>
      {detail ? (
        <p className="mt-2 text-sm text-[var(--muted)]">{detail}</p>
      ) : null}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="border border-red-300 bg-red-50 px-4 py-6 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
      {message}
    </div>
  );
}
