import { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { Save, Play, Plus } from 'lucide-react';

export default function PolicyEditor() {
  const [policies, setPolicies] = useState<string[]>([]);
  const [selectedPolicy, setSelectedPolicy] = useState<string>('');
  const [policyContent, setPolicyContent] = useState<string>('');
  
  const [inputJson, setInputJson] = useState<string>('{\n  "workspace": {\n    "name": "ws-enterprise-prod",\n    "type": "enterprise",\n    "environment": "prod"\n  },\n  "resource": {\n    "id": "example-cluster",\n    "type": "cluster",\n    "attributes": {}\n  }\n}');
  const [outputJson, setOutputJson] = useState<string>('{}');
  
  const [evaluating, setEvaluating] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchPolicies();
  }, []);

  const fetchPolicies = async () => {
    try {
      const res = await fetch('/api/v1/policies');
      const data = await res.json();
      setPolicies(data);
      if (data.length > 0 && !selectedPolicy) {
        loadPolicy(data[0]);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const loadPolicy = async (name: string) => {
    try {
      const res = await fetch(`/api/v1/policies/${name}`);
      const data = await res.json();
      setSelectedPolicy(name);
      setPolicyContent(data.content);
    } catch (e) {
      console.error(e);
    }
  };

  const handleSave = async () => {
    if (!selectedPolicy) return;
    setSaving(true);
    try {
      await fetch(`/api/v1/policies/${selectedPolicy}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: policyContent })
      });
      await fetchPolicies();
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const handleEvaluate = async () => {
    setEvaluating(true);
    try {
      const parsedInput = JSON.parse(inputJson);
      const queryName = selectedPolicy.replace('.rego', '');
      
      const res = await fetch('/api/v1/policies/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          policy_name: selectedPolicy,
          query: `data.databricks.governance.${queryName}`,
          input_data: parsedInput
        })
      });
      
      const data = await res.json();
      setOutputJson(JSON.stringify(data, null, 2));
    } catch (e: any) {
      setOutputJson(JSON.stringify({ error: e.message || 'Invalid JSON Input' }, null, 2));
    } finally {
      setEvaluating(false);
    }
  };

  const handleNew = () => {
    const name = prompt('Enter new policy name (e.g. my_policy.rego):');
    if (name) {
      setSelectedPolicy(name.endsWith('.rego') ? name : `${name}.rego`);
      setPolicyContent('package databricks.governance.' + name.replace('.rego', '') + '\n\n# Your policy logic here\n');
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Policy Editor & Playground</h1>
          <p className="text-gray-500 mt-1">Author Rego policies and test them instantly against simulated inputs.</p>
        </div>
      </div>

      <div className="flex flex-1 gap-4 overflow-hidden">
        {/* Left pane: File explorer & Policy Editor */}
        <div className="w-1/2 flex flex-col bg-white rounded-lg shadow border border-gray-200">
          <div className="flex items-center justify-between p-3 border-b border-gray-200 bg-gray-50">
            <div className="flex items-center gap-2">
              <select 
                className="text-sm border-gray-300 rounded-md bg-white px-2 py-1 outline-none focus:ring-2 focus:ring-blue-500"
                value={selectedPolicy}
                onChange={(e) => loadPolicy(e.target.value)}
              >
                <option value="" disabled>Select a policy</option>
                {policies.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
              <button onClick={handleNew} className="p-1 text-gray-500 hover:bg-gray-200 rounded" title="New Policy">
                <Plus className="w-4 h-4" />
              </button>
            </div>
            <button 
              onClick={handleSave} 
              disabled={saving || !selectedPolicy}
              className="flex items-center gap-1 px-3 py-1 bg-primary text-white text-sm rounded hover:opacity-90 disabled:opacity-50"
            >
              <Save className="w-4 h-4" /> Save
            </button>
          </div>
          <div className="flex-1">
            <Editor
              height="100%"
              defaultLanguage="ruby" // Monaco doesn't have native Rego syntax highlighting, ruby is a decent fallback for styling
              value={policyContent}
              onChange={(v) => setPolicyContent(v || '')}
              theme="vs-light"
              options={{ minimap: { enabled: false }, fontSize: 14 }}
            />
          </div>
        </div>

        {/* Right pane: Split vertically (Input / Output) */}
        <div className="w-1/2 flex flex-col gap-4">
          <div className="flex-1 flex flex-col bg-white rounded-lg shadow border border-gray-200">
            <div className="flex items-center justify-between p-3 border-b border-gray-200 bg-gray-50">
              <span className="text-sm font-semibold text-gray-700">Input Data (JSON)</span>
              <button 
                onClick={handleEvaluate} 
                disabled={evaluating || !selectedPolicy}
                className="flex items-center gap-1 px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
              >
                <Play className="w-4 h-4" /> Evaluate
              </button>
            </div>
            <div className="flex-1">
              <Editor
                height="100%"
                defaultLanguage="json"
                value={inputJson}
                onChange={(v) => setInputJson(v || '')}
                theme="vs-light"
                options={{ minimap: { enabled: false }, fontSize: 14 }}
              />
            </div>
          </div>

          <div className="flex-1 flex flex-col bg-white rounded-lg shadow border border-gray-200">
            <div className="p-3 border-b border-gray-200 bg-gray-50">
              <span className="text-sm font-semibold text-gray-700">Evaluation Output</span>
            </div>
            <div className="flex-1">
              <Editor
                height="100%"
                defaultLanguage="json"
                value={outputJson}
                theme="vs-light"
                options={{ minimap: { enabled: false }, fontSize: 14, readOnly: true }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
