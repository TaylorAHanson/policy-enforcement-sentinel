import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "../lib/utils";
import { useToastStore, type ToastTone } from "../store/toastStore";

const TONES: Record<ToastTone, { cls: string; Icon: typeof Info }> = {
  info: { cls: "border-info/40 text-info", Icon: Info },
  success: { cls: "border-success/40 text-success", Icon: CheckCircle2 },
  warning: { cls: "border-warning/40 text-warning", Icon: AlertTriangle },
  danger: { cls: "border-danger/50 text-danger", Icon: XCircle },
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (!toasts.length) return null;

  return (
    <div
      // `polite` rather than `assertive`: a success confirmation should not
      // interrupt a screen reader mid-sentence.
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[380px] max-w-[calc(100vw-2rem)] flex-col gap-2"
    >
      {toasts.map(({ id, tone, title, description }) => {
        const { cls, Icon } = TONES[tone];
        return (
          <div
            key={id}
            className={cn(
              "pointer-events-auto flex items-start gap-3 rounded-lg border bg-surface-overlay px-4 py-3 shadow-lg animate-slide-up",
              cls,
            )}
          >
            <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium text-content">{title}</p>
              {description && (
                <p className="mt-0.5 break-words text-xs leading-relaxed text-content-muted">
                  {description}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => dismiss(id)}
              aria-label="Dismiss"
              className="-mr-1 -mt-0.5 shrink-0 rounded p-1 text-content-subtle transition-colors hover:text-content"
            >
              <X className="size-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
