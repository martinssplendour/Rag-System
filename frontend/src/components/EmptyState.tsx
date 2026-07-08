import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  detail,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className="empty-state">
      <div aria-hidden="true">{icon}</div>
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}
