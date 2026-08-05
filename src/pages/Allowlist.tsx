import { useState, useEffect } from 'react';
import { ShieldCheck, Plus, Trash2, Search, RefreshCw, X } from 'lucide-react';
import type { AllowlistEntry } from '../services/api';

export default function Allowlist() {
  const [entries, setEntries] = useState<AllowlistEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  
  const [showAddModal, setShowAddModal] = useState(false);
  const [newEntry, setNewEntry] = useState({
    resource_id: '',
    resource_type: 'app',
    workspace: 'ws-enterprise-prod',
    justification: ''
  });

  const fetchEntries = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/allowlist');
      const data = await res.json();
      setEntries(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error(e);
      setEntries([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEntries();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showAddModal) {
        setShowAddModal(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showAddModal]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await fetch('/api/v1/allowlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newEntry)
      });
      setShowAddModal(false);
      setNewEntry({ resource_id: '', resource_type: 'app', workspace: 'ws-enterprise-prod', justification: '' });
      fetchEntries();
    } catch (e) {
      console.error(e);
      alert('Failed to add entry');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to remove this exception?')) return;
    try {
      await fetch(`/api/v1/allowlist/${id}`, { method: 'DELETE' });
      fetchEntries();
    } catch (e) {
      console.error(e);
      alert('Failed to delete entry');
    }
  };

  const filteredEntries = entries.filter(e => 
    !searchQuery || 
    e.resource_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
    e.workspace.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Policy Allowlist</h1>
          <p className="text-slate-400 mt-1 text-sm">Manage exceptions to governance policies across workspaces.</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="btn-primary"
        >
          <Plus className="w-4 h-4 mr-2" />
          Add Exception
        </button>
      </div>

      <div className="bg-[#11151c] rounded-xl shadow-lg border border-slate-800 overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 border-b border-slate-800">
          <div className="relative w-full md:w-80">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
              <input
                type="text"
                placeholder="Search resource or workspace..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex h-9 w-full rounded-[4px] border border-slate-700 bg-[#0b0f15] pl-9 pr-3 py-1 text-[13px] text-slate-200 placeholder-slate-500 shadow-sm focus:outline-none focus:ring-1 focus:ring-[#8acaff] focus:border-[#8acaff] transition-colors"
              />
          </div>
          <button onClick={fetchEntries} className="p-2 text-slate-400 hover:text-slate-200 hover:bg-[#1b232d] rounded transition-colors" title="Refresh">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="bg-[#161b22] text-slate-400 font-medium border-b border-slate-800">
              <tr>
                <th className="p-3 pl-5 font-medium">Resource</th>
                <th className="p-3 font-medium">Workspace</th>
                <th className="p-3 w-1/3 font-medium">Justification</th>
                <th className="p-3 font-medium">Status</th>
                <th className="p-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {loading && entries.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-slate-500">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-slate-400" />
                    Loading exceptions...
                  </td>
                </tr>
              ) : filteredEntries.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-slate-500">
                    No allowlist exceptions found.
                  </td>
                </tr>
              ) : (
                filteredEntries.map(entry => (
                  <tr key={entry.id} className="hover:bg-[#1b232d] transition-colors">
                    <td className="p-3 pl-5 font-mono text-xs text-slate-200 align-top">
                      <div className="flex flex-col gap-1.5">
                        <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider font-sans bg-[#0b0f15] border border-slate-700 px-1.5 py-0.5 rounded w-max inline-block">
                          {entry.resource_type}
                        </span>
                        <span className="break-all">{entry.resource_id}</span>
                      </div>
                    </td>
                    <td className="p-3 align-top text-slate-300">
                      {entry.workspace}
                    </td>
                    <td className="p-3 align-top text-slate-400 break-words">
                      {entry.justification}
                    </td>
                    <td className="p-3 align-top">
                      <span className={`px-2.5 py-1 rounded-full text-[10px] uppercase font-bold border ${
                        entry.status === 'approved' ? 'bg-green-950/30 text-green-400 border-green-900/50' : 'bg-yellow-950/30 text-yellow-400 border-yellow-900/50'
                      }`}>
                        {entry.status}
                      </span>
                    </td>
                    <td className="p-3 text-right align-top">
                      <button 
                        onClick={() => handleDelete(entry.id)}
                        className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-950/50 rounded transition-colors"
                        title="Delete Exception"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b0f15]/80 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="bg-[#11151c] border border-slate-800 rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in zoom-in-95">
            <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-[#161b22] shrink-0">
                <h3 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
                    <ShieldCheck className="w-5 h-5 text-blue-500" />
                    Add Policy Exception
                </h3>
                <button onClick={() => setShowAddModal(false)} className="p-2 rounded-full hover:bg-slate-800 transition-colors">
                    <X className="w-5 h-5 text-slate-400" />
                </button>
            </div>
            <form onSubmit={handleAdd} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Resource ID</label>
                <input
                  required
                  type="text"
                  value={newEntry.resource_id}
                  onChange={e => setNewEntry({...newEntry, resource_id: e.target.value})}
                  className="w-full rounded-[4px] border border-slate-700 bg-[#0b0f15] text-slate-200 placeholder-slate-500 px-3 py-2 text-[13px] focus:outline-none focus:ring-1 focus:ring-[#8acaff] focus:border-[#8acaff] transition-colors"
                  placeholder="e.g., cluster-12345 or /Shared/app"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1.5">Type</label>
                  <select
                    value={newEntry.resource_type}
                    onChange={e => setNewEntry({...newEntry, resource_type: e.target.value})}
                    className="w-full rounded-[4px] border border-slate-700 bg-[#0b0f15] text-slate-200 px-3 py-2 text-[13px] focus:outline-none focus:ring-1 focus:ring-[#8acaff] focus:border-[#8acaff] transition-colors"
                  >
                    <option value="app">App</option>
                    <option value="cluster">Cluster</option>
                    <option value="job">Job</option>
                    <option value="sql_warehouse">SQL Warehouse</option>
                    <option value="dashboard">Dashboard</option>
                    <option value="genie_space">Genie Space</option>
                    <option value="notebook">Notebook</option>
                    <option value="table">Table</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-1.5">Workspace</label>
                  <input
                    required
                    type="text"
                    value={newEntry.workspace}
                    onChange={e => setNewEntry({...newEntry, workspace: e.target.value})}
                    className="w-full rounded-[4px] border border-slate-700 bg-[#0b0f15] text-slate-200 px-3 py-2 text-[13px] focus:outline-none focus:ring-1 focus:ring-[#8acaff] focus:border-[#8acaff] transition-colors"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Justification</label>
                <textarea
                  required
                  rows={3}
                  value={newEntry.justification}
                  onChange={e => setNewEntry({...newEntry, justification: e.target.value})}
                  className="w-full rounded-[4px] border border-slate-700 bg-[#0b0f15] text-slate-200 placeholder-slate-500 px-3 py-2 text-[13px] focus:outline-none focus:ring-1 focus:ring-[#8acaff] focus:border-[#8acaff] transition-colors resize-none"
                  placeholder="Explain why this resource is exempt from standard policies..."
                />
              </div>
              
              <div className="pt-4 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 bg-[#1b232d] border border-slate-700 text-slate-300 rounded hover:bg-[#252f3d] text-sm font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn-primary"
                >
                  Save Exception
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}