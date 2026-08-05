import * as React from "react";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "./button";

/**
 * A modal built on the native `<dialog>` element, which brings focus trapping,
 * inertness of the page behind it, and Escape handling without a dependency.
 *
 * Escape is intercepted when `dismissible` is false. The enforcement
 * confirmation uses that: a dialog asking you to type a workspace name before
 * destroying anything in it should not be dismissable by a stray keypress.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  tone = "default",
  dismissible = true,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  size?: "sm" | "md" | "lg";
  tone?: "default" | "danger";
  dismissible?: boolean;
}) {
  const ref = React.useRef<HTMLDialogElement>(null);

  React.useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  React.useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const handleCancel = (event: Event) => {
      event.preventDefault();
      if (dismissible) onClose();
    };
    node.addEventListener("cancel", handleCancel);
    return () => node.removeEventListener("cancel", handleCancel);
  }, [dismissible, onClose]);

  const width = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl" }[size];

  return (
    <dialog
      ref={ref}
      className={cn(
        "m-auto w-[92vw] rounded-lg border bg-surface p-0 text-content backdrop:bg-black/60 backdrop:backdrop-blur-sm animate-slide-up",
        tone === "danger" ? "border-danger/50" : "border-border-strong",
        width,
      )}
      onClick={(event) => {
        // Clicking the backdrop closes it: the dialog element fills the modal
        // box, so a click landing on the element itself is a click outside the
        // content.
        if (dismissible && event.target === ref.current) onClose();
      }}
    >
      <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <h2
            className={cn(
              "text-sm font-semibold",
              tone === "danger" ? "text-danger" : "text-content",
            )}
          >
            {title}
          </h2>
          {description && (
            <p className="mt-1 text-xs text-content-muted leading-relaxed">
              {description}
            </p>
          )}
        </div>
        {dismissible && (
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 -mt-1 shrink-0"
          >
            <X />
          </Button>
        )}
      </div>

      {children && <div className="px-5 py-4">{children}</div>}

      {footer && (
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          {footer}
        </div>
      )}
    </dialog>
  );
}

/**
 * A confirmation that requires typing an exact phrase.
 *
 * Used wherever an action cannot be undone. A checkbox or a second "Are you
 * sure?" both get clicked reflexively; typing the workspace name does not
 * happen by accident, and it forces you to read which workspace you are in.
 */
export function ConfirmPhraseDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  phrase,
  confirmLabel = "Confirm",
  loading,
  children,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  phrase: string;
  confirmLabel?: string;
  loading?: boolean;
  children?: React.ReactNode;
}) {
  const [typed, setTyped] = React.useState("");
  const matches = typed.trim() === phrase;

  React.useEffect(() => {
    if (open) setTyped("");
  }, [open]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      tone="danger"
      dismissible={!loading}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={onConfirm}
            disabled={!matches}
            loading={loading}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
      <div className="mt-4 flex flex-col gap-1.5">
        <label htmlFor="confirm-phrase" className="text-xs text-content-muted">
          Type <span className="font-mono text-danger">{phrase}</span> to continue.
        </label>
        <input
          id="confirm-phrase"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          className="h-8 w-full rounded-md border border-border-strong bg-surface-raised px-2.5 font-mono text-[13px] text-content focus-visible:border-danger"
        />
      </div>
    </Dialog>
  );
}
