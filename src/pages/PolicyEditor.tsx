import { useState, useEffect, useRef } from 'react';
import Editor, { DiffEditor } from '@monaco-editor/react';
import { Save, Play, Plus, Search, ChevronDown, Check, X, AlertTriangle, RefreshCw, GitPullRequest, ExternalLink } from 'lucide-react';

export default function PolicyEditor() {
  const [policies, setPolicies] = useState<string[]>([]);
  const [selectedPolicy, setSelectedPolicy] = useState<string>('');
  const [policyContent, setPolicyContent] = useState<string>('');
  const [originalContent, setOriginalContent] = useState<string>('');
  const [showDiffModal, setShowDiffModal] = useState(false);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [githubEnabled, setGithubEnabled] = useState(false);
  const [targetBranch, setTargetBranch] = useState('main');
  const [prUrl, setPrUrl] = useState<string | null>(null);
  
  const [inputJson, setInputJson] = useState<string>('{\n  "workspace": {\n    "name": "ws-enterprise-prod",\n    "type": "enterprise",\n    "environment": "prod"\n  },\n  "resource": {\n    "id": "example-cluster",\n    "type": "cluster",\n    "attributes": {}\n  }\n}');
  const [outputJson, setOutputJson] = useState<string>('{}');
  
  const [evaluating, setEvaluating] = useState(false);
  const [saving, setSaving] = useState(false);

  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchConfig();
    fetchPolicies();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showDiffModal) {
        setShowDiffModal(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showDiffModal]);

  const fetchConfig = async () => {
    try {
      const res = await fetch('/api/v1/policies/config');
      const data = await res.json();
      setGithubEnabled(data.github_enabled);
      setTargetBranch(data.target_branch || 'main');
    } catch (e) {
      console.error("Failed to fetch config", e);
    }
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filteredPolicies = policies.filter(p => p.toLowerCase().includes(searchQuery.toLowerCase()));

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

  const getDefaultInputForPolicy = (policyName: string) => {
    const baseWorkspace = {
      "name": "ws-enterprise-prod",
      "type": "enterprise",
      "environment": "prod"
    };
    
    let resourceType = "unknown";
    let attributes: any = {};
    
    if (policyName.includes("cluster")) {
      resourceType = "cluster";
      attributes = {
        "node_type_id": "i3.xlarge",
        "custom_tags": {}
      };
    } else if (policyName.includes("job")) {
      resourceType = "job";
      attributes = {
        "creator": "user@example.com",
        "settings": {
          "email_notifications": {}
        }
      };
    } else if (policyName.includes("sql_warehouse") || policyName.includes("warehouse")) {
      resourceType = "sql_warehouse";
      attributes = {
        "channel": "preview",
        "cluster_size": "Large"
      };
    } else if (policyName.includes("model_serving")) {
      resourceType = "model_serving_endpoint";
      attributes = {
        "name": "my-endpoint",
        "custom_tags": {}
      };
    } else if (policyName.includes("spark_declarative_pipelines") || policyName.includes("pipeline") || policyName.includes("dlt")) {
      resourceType = "pipeline";
      attributes = {
        "serverless": false,
        "continuous": false
      };
    } else if (policyName.includes("service_principal")) {
      resourceType = "service_principal";
      attributes = {
        "display_name": "example-sp",
        "active": true
      };
    }
    
    return JSON.stringify({
      workspace: baseWorkspace,
      resource: {
        id: `example-${resourceType.replace(/_/g, '-')}`,
        type: resourceType,
        attributes: attributes
      }
    }, null, 2);
  };

  const loadPolicy = async (name: string) => {
    try {
      const res = await fetch(`/api/v1/policies/${name}`);
      const data = await res.json();
      setSelectedPolicy(name);
      setPolicyContent(data.content);
      setOriginalContent(data.content);
      setValidationErrors([]);
      setPrUrl(null);
      setInputJson(getDefaultInputForPolicy(name));
    } catch (e) {
      console.error(e);
    }
  };

  const handleValidateAndDiff = async () => {
    if (!selectedPolicy) return;
    setSaving(true);
    setValidationErrors([]);
    setPrUrl(null);
    try {
      const res = await fetch('/api/v1/policies/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policy_name: selectedPolicy, content: policyContent })
      });
      const data = await res.json();
      
      if (!data.valid) {
        setValidationErrors(data.errors || ['Validation failed']);
        setOutputJson(JSON.stringify({ 
          status: "Validation Failed", 
          errors: data.errors 
        }, null, 2));
        return;
      }
      
      // If validation succeeds, clear output pane of any previous validation errors
      if (validationErrors.length > 0) {
        setOutputJson('{}');
      }
      
      if (policyContent !== originalContent) {
        setShowDiffModal(true);
      } else {
        // No changes, just perform a silent save to give feedback
        await executeSave();
      }
    } catch (e) {
      console.error(e);
      setValidationErrors(['Error connecting to validation service']);
    } finally {
      setSaving(false);
    }
  };

  const executeSave = async () => {
    if (!selectedPolicy) return;
    setSaving(true);
    try {
      const endpoint = githubEnabled ? `/api/v1/policies/${selectedPolicy}/pr` : `/api/v1/policies/${selectedPolicy}`;
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: policyContent })
      });
      
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to save or create PR");
      }
      
      setOriginalContent(policyContent);
      
      if (githubEnabled && data.pr_url) {
        setPrUrl(data.pr_url);
        // We do NOT close the modal automatically here so they can see the success link.
      } else {
        setShowDiffModal(false);
      }
      
      await fetchPolicies();
    } catch (e: any) {
      console.error(e);
      alert(e.message || "An error occurred while saving.");
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
          content: policyContent,
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
          <h1 className="text-2xl font-bold text-slate-100">Policy Editor & Playground</h1>
          <p className="text-slate-400 mt-1 text-sm">Author Rego policies and test them instantly against simulated inputs.</p>
        </div>
      </div>

      <div className="flex flex-1 gap-4 overflow-hidden">
        {/* Left pane: File explorer & Policy Editor */}
        <div className="w-1/2 flex flex-col bg-[#11151c] rounded-xl shadow-lg border border-slate-800 overflow-hidden">
          <div className="flex items-center justify-between p-3 border-b border-slate-800 bg-[#161b22]">
            <div className="flex items-center gap-3">
              <div className="relative w-64" ref={dropdownRef}>
                <div 
                  className={`flex items-center justify-between w-full border rounded-[4px] bg-[#0b0f15] text-slate-200 px-3 py-1.5 text-[13px] cursor-pointer transition-colors ${isDropdownOpen ? 'border-[#8acaff]' : 'border-slate-700 hover:border-slate-600'}`}
                  onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                >
                  <span className="truncate mr-2 font-medium">{selectedPolicy || "Select a policy..."}</span>
                  <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
                </div>
                
                {isDropdownOpen && (
                  <div className="absolute top-full left-0 mt-1 w-80 bg-[#11151c] border border-slate-700 rounded-[4px] shadow-xl z-50 overflow-hidden">
                    <div className="p-2 border-b border-slate-800">
                      <div className="relative">
                        <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
                        <input 
                          type="text" 
                          autoFocus
                          className="w-full bg-[#0b0f15] border border-slate-700 rounded-[4px] pl-8 pr-3 py-1.5 text-[13px] text-slate-200 placeholder-slate-500 focus:outline-none focus:border-[#8acaff] transition-colors"
                          placeholder="Search policies..."
                          value={searchQuery}
                          onChange={e => setSearchQuery(e.target.value)}
                        />
                      </div>
                    </div>
                    <div className="max-h-60 overflow-y-auto p-1">
                      {filteredPolicies.length === 0 ? (
                        <div className="px-3 py-4 text-center text-slate-500 text-[13px]">No policies found</div>
                      ) : (
                        filteredPolicies.map(p => (
                          <div 
                            key={p}
                            className={`flex items-center justify-between px-3 py-2 text-[13px] rounded-[4px] cursor-pointer ${selectedPolicy === p ? 'bg-[#8acaff14] text-[#8acaff] font-medium' : 'text-slate-300 hover:bg-[#1b232d] hover:text-slate-200'}`}
                            onClick={() => {
                              loadPolicy(p);
                              setIsDropdownOpen(false);
                              setSearchQuery('');
                            }}
                          >
                            <span className="truncate">{p}</span>
                            {selectedPolicy === p && <Check className="w-3.5 h-3.5 shrink-0" />}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>
              <button onClick={handleNew} className="flex items-center gap-1 p-1.5 px-2 text-[13px] font-medium text-slate-400 hover:text-[#8acaff] hover:bg-[#8acaff14] rounded-[4px] transition-colors border border-transparent hover:border-[#8acaff]/30" title="New Policy">
                <Plus className="w-4 h-4" /> New
              </button>
            </div>
            <button 
              onClick={handleValidateAndDiff} 
              disabled={saving || !selectedPolicy}
              className="btn-primary gap-1.5"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : 
               (githubEnabled ? <GitPullRequest className="w-4 h-4" /> : <Save className="w-4 h-4" />)} 
              {githubEnabled ? 'Propose Change' : 'Save'}
            </button>
          </div>
          <div className="flex-1 bg-[#1e1e1e]">
            <Editor
              height="100%"
              defaultLanguage="ruby" // Monaco doesn't have native Rego syntax highlighting, ruby is a decent fallback for styling
              value={policyContent}
              onChange={(v) => setPolicyContent(v || '')}
              theme="vs-dark"
              options={{ minimap: { enabled: false }, fontSize: 14, padding: { top: 16 } }}
            />
          </div>
          {validationErrors.length > 0 && (
            <div className="bg-red-950/30 border-t border-red-900/50 p-3 shrink-0 max-h-40 overflow-y-auto">
              <h4 className="text-red-400 text-sm font-medium flex items-center mb-1"><AlertTriangle className="w-4 h-4 mr-1" /> Validation Errors</h4>
              <ul className="list-disc pl-5 text-red-300 text-xs space-y-1">
                {validationErrors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}
        </div>

        {/* Right pane: Split vertically (Input / Output) */}
        <div className="w-1/2 flex flex-col gap-4">
          <div className="flex-1 flex flex-col bg-[#11151c] rounded-xl shadow-lg border border-slate-800 overflow-hidden">
            <div className="flex items-center justify-between p-3 border-b border-slate-800 bg-[#161b22]">
              <span className="text-sm font-medium text-slate-300">Input Data (JSON)</span>
              <button 
                onClick={handleEvaluate} 
                disabled={evaluating || !selectedPolicy}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-transparent text-[#8acaff] hover:bg-[#8acaff14] text-[13px] font-medium rounded-[4px] disabled:opacity-50 transition-colors"
              >
                <Play className="w-4 h-4" /> Evaluate
              </button>
            </div>
            <div className="flex-1 bg-[#1e1e1e]">
              <Editor
                height="100%"
                defaultLanguage="json"
                value={inputJson}
                onChange={(v) => setInputJson(v || '')}
                theme="vs-dark"
                options={{ minimap: { enabled: false }, fontSize: 14, padding: { top: 16 } }}
              />
            </div>
          </div>

          <div className="flex-1 flex flex-col bg-[#11151c] rounded-xl shadow-lg border border-slate-800 overflow-hidden">
            <div className="p-3 border-b border-slate-800 bg-[#161b22]">
              <span className="text-sm font-medium text-slate-300">Evaluation Output</span>
            </div>
            <div className="flex-1 bg-[#1e1e1e]">
              <Editor
                height="100%"
                defaultLanguage="json"
                value={outputJson}
                theme="vs-dark"
                options={{ minimap: { enabled: false }, fontSize: 14, readOnly: true, padding: { top: 16 } }}
              />
            </div>
          </div>
        </div>
      </div>

      {showDiffModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b0f15]/80 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="bg-[#11151c] border border-slate-800 rounded-xl shadow-2xl w-full max-w-6xl h-[80vh] flex flex-col overflow-hidden animate-in zoom-in-95">
            <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-[#161b22] shrink-0">
                <h3 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
                    Review Policy Changes: {selectedPolicy}
                </h3>
                <button onClick={() => setShowDiffModal(false)} className="p-2 rounded-full hover:bg-slate-800 transition-colors">
                    <X className="w-5 h-5 text-slate-400" />
                </button>
            </div>
            <div className="flex-1 bg-[#1e1e1e]">
              {prUrl ? (
                <div className="h-full flex flex-col items-center justify-center bg-[#0b0f15] text-slate-300 p-8">
                  <div className="w-16 h-16 bg-[#8acaff14] rounded-full flex items-center justify-center mb-6">
                    <Check className="w-8 h-8 text-[#8acaff]" />
                  </div>
                  <h4 className="text-xl font-medium text-slate-100 mb-2">Pull Request Created!</h4>
                  <p className="text-slate-400 mb-6 max-w-md text-center">
                    Your policy changes have been successfully proposed. Please review and merge the pull request to apply them to <code>{targetBranch}</code>.
                  </p>
                  <a 
                    href={prUrl} 
                    target="_blank" 
                    rel="noreferrer"
                    className="flex items-center gap-2 px-4 py-2 bg-[#1b232d] text-[#8acaff] border border-[#8acaff]/30 rounded hover:bg-[#8acaff14] font-medium transition-colors"
                  >
                    View Pull Request <ExternalLink className="w-4 h-4" />
                  </a>
                </div>
              ) : (
                <DiffEditor
                  height="100%"
                  language="ruby"
                  original={originalContent}
                  modified={policyContent}
                  theme="vs-dark"
                  options={{ minimap: { enabled: false }, fontSize: 14, renderSideBySide: true, readOnly: true }}
                />
              )}
            </div>
            <div className="p-4 border-t border-slate-800 bg-[#161b22] flex justify-end gap-3 shrink-0">
                <button 
                  className="px-4 py-2 bg-[#1b232d] text-slate-300 border border-slate-700 rounded hover:bg-[#252f3d] text-sm font-medium transition-colors"
                  onClick={() => setShowDiffModal(false)}
                >
                  {prUrl ? 'Close' : 'Cancel'}
                </button>
                {!prUrl && (
                  <button 
                      disabled={saving}
                      onClick={executeSave}
                      className="btn-primary gap-2"
                  >
                      {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : 
                       (githubEnabled ? <GitPullRequest className="w-4 h-4" /> : <Check className="w-4 h-4" />)}
                      {githubEnabled ? 'Create Pull Request' : 'Confirm & Save'}
                  </button>
                )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}