import type { ReactNode } from "react";

export function NavButton({
  icon,
  label,
  isActive,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`nav-button ${isActive ? "active" : ""}`} type="button" onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}
