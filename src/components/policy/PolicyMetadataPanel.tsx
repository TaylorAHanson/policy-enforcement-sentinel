import { Badge, SeverityBadge } from "../ui/badge";
import { Alert, EmptyState } from "../ui/feedback";
import { TierBadge } from "../safety/TierBadge";
import { humanize } from "../../lib/utils";
import type { PolicyMetadata } from "../../services/api";

/**
 * The policy's annotations and per-rule metadata, read back from OPA rather
 * than from the editor buffer. That distinction matters: this shows what the
 * engine will actually evaluate, so it reflects the last saved version and not
 * whatever is currently being typed.
 */
export function PolicyMetadataPanel({
  metadata,
  dirty,
}: {
  metadata: PolicyMetadata | null;
  dirty: boolean;
}) {
  if (!metadata) {
    return (
      <EmptyState
        title="No metadata"
        description="This policy has no METADATA annotations or rule_metadata block, or it does not currently compile."
      />
    );
  }

  const escalated = metadata.rules.filter((r) => r.tier >= 2);

  return (
    <div className="space-y-4 p-4">
      {dirty && (
        <Alert tone="info" title="Showing the saved version">
          You have unsaved edits. This panel reflects what OPA has loaded, which
          updates when you save.
        </Alert>
      )}

      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-content">{metadata.title}</h3>
        {metadata.description && (
          <p className="whitespace-pre-line text-xs leading-relaxed text-content-muted">
            {metadata.description}
          </p>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-border bg-surface-raised px-4 py-3 text-xs">
        <Meta label="Owner" value={metadata.owner || "—"} />
        <Meta label="Domain" value={humanize(metadata.domain) || "—"} />
        <Meta label="Resource type" value={humanize(metadata.resource_type) || "—"} />
        <Meta label="Rules" value={String(metadata.rule_count)} />
        {metadata.authors.length > 0 && (
          <div className="col-span-2">
            <dt className="text-2xs uppercase tracking-wider text-content-subtle">
              Authors
            </dt>
            <dd className="mt-0.5 text-content">{metadata.authors.join(", ")}</dd>
          </div>
        )}
      </dl>

      {escalated.length > 0 && (
        // Worth calling out loudly. Everything ships at Tier 1, so a Tier 2+
        // rule means somebody deliberately escalated it and the reviewer of
        // this policy should know without reading all sixty lines of metadata.
        <Alert
          tone={escalated.some((r) => r.tier >= 3) ? "danger" : "warning"}
          title={`${escalated.length} rule${escalated.length === 1 ? "" : "s"} escalated beyond notify`}
        >
          {escalated.map((r) => r.id).join(", ")} can change or remove resources.
        </Alert>
      )}

      <div className="space-y-2">
        <h4 className="text-2xs font-semibold uppercase tracking-wider text-content-subtle">
          Rules
        </h4>
        {metadata.rules.map((rule) => (
          <div
            key={rule.rule}
            className="rounded-md border border-border bg-surface-raised px-3 py-2.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <code className="font-mono text-xs text-content">{rule.id}</code>
              <SeverityBadge severity={rule.severity} />
              <Badge variant="outline">{humanize(rule.category)}</Badge>
              <span className="flex-1" />
              <code className="font-mono text-2xs text-content-muted">
                {rule.requested_action}
              </code>
              <TierBadge tier={rule.tier} />
              {rule.destructive && <Badge variant="danger">destructive</Badge>}
            </div>
            <p className="mt-1.5 text-2xs leading-relaxed text-content-muted">
              {rule.description}
            </p>
            <div className="mt-1 flex items-center gap-3 text-2xs text-content-subtle">
              <code className="font-mono">{rule.rule}</code>
              {rule.escalate_after_days > 0 && (
                <span>escalates after {rule.escalate_after_days} days</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-2xs uppercase tracking-wider text-content-subtle">{label}</dt>
      <dd className="mt-0.5 text-content">{value}</dd>
    </div>
  );
}
