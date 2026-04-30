import { Code, Database, ShieldAlert } from 'lucide-react';

export default function QuickReference() {
  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Policy As Code: Quick Reference</h1>
        <p className="text-gray-500 mt-2 max-w-3xl leading-relaxed">
          <strong>Policy As Code.</strong> This is a magic phrase. Enterprise architects and security architects go bananas for it. 
          The Sentinel uses <strong>OPA (Open Policy Agent)</strong>—which takes a policy in one hand, a set of facts in the other, and returns "yes" or "no" like a boolean evaluation engine. 
          The language these policies are written in is <strong>Rego</strong>, a declarative language whose superpower is reusability (DRY not WET).
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* Basic Structure */}
        <div className="bg-white p-6 rounded-lg shadow border border-gray-200">
          <div className="flex items-center gap-2 mb-4 text-blue-600">
            <Code className="w-5 h-5" />
            <h2 className="text-lg font-semibold text-gray-900">Policy Structure</h2>
          </div>
          <p className="text-sm text-gray-600 mb-3">All policies must return a specific object structure to interface with the Sentinel:</p>
          <pre className="bg-gray-50 p-3 rounded-md text-xs font-mono text-gray-800 border border-gray-100 overflow-x-auto">
{`package databricks.governance.my_policy

default is_violation = false
default action = "ALLOW"
default severity = "LOW"
default reason = "No issues found"

# Trigger a warning
is_violation {
  input.resource.type == "cluster"
  not input.resource.attributes.custom_tags
}

action = "WARN" { is_violation }
severity = "MEDIUM" { is_violation }
reason = "Cluster is missing required tags." { is_violation }`}
          </pre>
        </div>

        {/* Input Schema */}
        <div className="bg-white p-6 rounded-lg shadow border border-gray-200">
          <div className="flex items-center gap-2 mb-4 text-green-600">
            <Database className="w-5 h-5" />
            <h2 className="text-lg font-semibold text-gray-900">Input Schema</h2>
          </div>
          <p className="text-sm text-gray-600 mb-3">The input data provided to OPA looks like this:</p>
          <pre className="bg-gray-50 p-3 rounded-md text-xs font-mono text-gray-800 border border-gray-100 overflow-x-auto">
{`{
  "workspace": {
    "name": "ws-enterprise-prod",
    "type": "enterprise",
    "environment": "prod"
  },
  "resource": {
    "id": "cluster-123",
    "type": "cluster",
    "attributes": {
      "cluster_name": "Shared Compute",
      "custom_tags": { "Team": "Data" }
    }
  },
  "allowlist_records": []
}`}
          </pre>
        </div>

        {/* Actions & Severities */}
        <div className="bg-white p-6 rounded-lg shadow border border-gray-200 md:col-span-2">
          <div className="flex items-center gap-2 mb-4 text-red-600">
            <ShieldAlert className="w-5 h-5" />
            <h2 className="text-lg font-semibold text-gray-900">Actions & Severities</h2>
          </div>
          <div className="grid grid-cols-2 gap-8">
            <div>
              <h3 className="font-medium text-gray-800 mb-2">Supported Actions</h3>
              <ul className="space-y-2 text-sm text-gray-600">
                <li><strong className="text-gray-900">KILL</strong> - Terminates/Deletes the resource.</li>
                <li><strong className="text-gray-900">WARN</strong> - Sends a warning notification but leaves resource intact.</li>
                <li><strong className="text-gray-900">CERTIFY</strong> - Marks a data product as certified.</li>
                <li><strong className="text-gray-900">UNCERTIFY</strong> - Revokes certification status.</li>
              </ul>
            </div>
            <div>
              <h3 className="font-medium text-gray-800 mb-2">Severity Levels</h3>
              <ul className="space-y-2 text-sm text-gray-600">
                <li><strong className="text-gray-900">CRITICAL</strong> - Immediate destructive action required.</li>
                <li><strong className="text-gray-900">HIGH</strong> - Major violation, normally triggers KILL.</li>
                <li><strong className="text-gray-900">MEDIUM</strong> - Important violation, triggers WARN or KILL depending on mode.</li>
                <li><strong className="text-gray-900">LOW</strong> - Minor violation, usually just audit logged.</li>
              </ul>
            </div>
          </div>
        </div>

        {/* Unvarnished Truth */}
        <div className="bg-gray-50 p-6 rounded-lg border border-gray-200 md:col-span-2 mt-4">
          <div className="flex items-center gap-2 mb-3 text-gray-800">
            <ShieldAlert className="w-5 h-5 text-gray-500" />
            <h2 className="text-lg font-semibold text-gray-900">The Unvarnished Truth</h2>
          </div>
          <ul className="list-disc pl-5 space-y-2 text-sm text-gray-700">
            <li><strong>Not a replacement for Unity Catalog:</strong> If you can manage it in Unity Catalog, prefer that.</li>
            <li><strong>We don't lock the platform down:</strong> There is a reason Databricks is flexible! We want users to build stuff.</li>
            <li><strong>This is reactive, not proactive:</strong> Do not count on this for mission-critical security that must be blocked inline.</li>
            <li><strong>The SP this runs as needs wide-ranging permissions:</strong> Consider the blast radius and Principle of Least Privilege (PLP).</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
