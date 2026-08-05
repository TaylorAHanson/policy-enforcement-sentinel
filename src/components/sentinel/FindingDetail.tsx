import { ShieldPlus } from "lucide-react";
import { Badge, SeverityBadge } from "../ui/badge";
import { Button } from "../ui/button";
import { Dialog } from "../ui/dialog";
import { Alert } from "../ui/feedback";
import { ActionCell, TierBadge } from "../safety/TierBadge";
import { formatTimestamp, humanize } from "../../lib/utils";
import type { Finding } from "../../services/api";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[128px_1fr] gap-3 py-1.5">
      <dt className="text-2xs uppercase tracking-wider text-content-subtle">{label}</dt>
      <dd className="min-w-0 break-words text-xs text-content">{children}</dd>
    </div>
  );
}

export function FindingDetail({
  finding,
  onClose,
  onAllowlist,
}: {
  finding: Finding | null;
  onClose: () => void;
  onAllowlist?: (finding: Finding) => void;
}) {
  if (!finding) return null;

  const isCheck = finding.kind === "check";

  return (
    <Dialog
      open={Boolean(finding)}
      onClose={onClose}
      size="lg"
      title={finding.resource_name || finding.resource_id}
      description={`${humanize(finding.resource_type)} in ${finding.workspace}`}
      footer={
        <>
          {onAllowlist && !isCheck && (
            <Button variant="secondary" onClick={() => onAllowlist(finding)}>
              <ShieldPlus />
              Request an exception
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {finding.downgraded && finding.downgrade_reason && (
          // The most important thing on this screen when it applies: the policy
          // asked for one thing and the safety gates produced another.
          <Alert tone="warning" title="This action was downgraded">
            {finding.downgrade_reason}
          </Alert>
        )}

        <div className="rounded-md border border-border bg-surface-raised px-4 py-3">
          <p className="text-[13px] leading-relaxed text-content">
            {finding.message || "No detail recorded."}
          </p>
        </div>

        <dl className="divide-y divide-border">
          <Row label="Result">
            {isCheck ? (
              <Badge variant="success">Compliant</Badge>
            ) : (
              <SeverityBadge severity={finding.severity} size="md" />
            )}
          </Row>

          <Row label="Resource id">
            <code className="font-mono text-2xs">{finding.resource_id}</code>
          </Row>

          {finding.owner && <Row label="Owner">{finding.owner}</Row>}

          <Row label="Policy">
            {finding.policy || "—"}
            {finding.rule_id && (
              <span className="text-content-subtle"> · {finding.rule_id}</span>
            )}
          </Row>

          {finding.policy_id && (
            <Row label="Rule id">
              <code className="font-mono text-2xs">{finding.policy_id}</code>
            </Row>
          )}

          {finding.category && <Row label="Category">{humanize(finding.category)}</Row>}

          {!isCheck && (
            <>
              <Row label="Action">
                <ActionCell
                  requestedAction={finding.requested_action}
                  effectiveAction={finding.effective_action}
                  tier={finding.tier}
                  requestedTier={finding.requested_tier}
                  executed={finding.executed}
                />
              </Row>
              <Row label="Tier">
                <div className="flex items-center gap-2">
                  <TierBadge tier={finding.tier} />
                  {finding.requested_tier != null &&
                    finding.requested_tier !== finding.tier && (
                      <span className="text-2xs text-content-subtle">
                        policy requested <TierBadge tier={finding.requested_tier} />
                      </span>
                    )}
                </div>
              </Row>
            </>
          )}

          <Row label="Recorded">{formatTimestamp(finding.created_at)}</Row>
        </dl>

        {finding.data && Object.keys(finding.data).length > 0 && (
          <details className="rounded-md border border-border bg-surface-raised">
            <summary className="cursor-pointer px-4 py-2 text-xs text-content-muted">
              Resource attributes as evaluated
            </summary>
            <pre className="max-h-64 overflow-auto border-t border-border px-4 py-3 text-2xs leading-relaxed text-content-muted">
              {JSON.stringify(finding.data, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </Dialog>
  );
}
