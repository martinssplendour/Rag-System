import { CheckCircle2, XCircle } from "lucide-react";

export function InlineAlert({ tone, message }: { tone: "error" | "success"; message: string }) {
  const Icon = tone === "error" ? XCircle : CheckCircle2;
  return (
    <div className={`inline-alert ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}
