import { useState, useEffect } from 'react';
import { RefreshCw, ShieldAlert, AlertTriangle, CheckCircle2, FileStack, ShieldCheck, ListChecks, X, Search, ChevronLeft, ChevronRight, ArrowRight } from 'lucide-react';

const formatReason = (v: any) => {
    if (v.violation_reasons && Array.isArray(v.violation_reasons) && v.violation_reasons.length > 0) {
        if (v.violation_reasons.length === 1) {
            return v.violation_reasons[0];
        }
        return (
            <ul className="list-disc pl-4 space-y-1 text-left">
                {v.violation_reasons.map((reason: string, i: number) => (
                    <li key={i}>{reason}</li>
                ))}
            </ul>
        );
    }
    return v.reason;
};

export default function SentinelDashboard() {
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<string>('all');
  
  const [executedActions, setExecutedActions] = useState<Record<string, { at: string }>>({});
  const [selectedViolation, setSelectedViolation] = useState<any | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  
  const [page, setPage] = useState(1);
  const pageSize = 10;

  const fetchRuns = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/sentinel/runs');
      const data = await res.json();
      setRuns(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
    const interval = setInterval(fetchRuns, 5000);
    return () => clearInterval(interval);
  }, []);

  const triggerRun = async (mode: 'audit' | 'enforce') => {
    setShowConfirmModal(false);
    setTriggering(true);
    try {
      await fetch(`/api/v1/sentinel/run?mode=${mode}`, { method: 'POST' });
      await fetchRuns();
    } catch (e) {
      console.error(e);
    } finally {
      setTriggering(false);
    }
  };

  const handleExecuteAction = async (runId: string, v: any) => {
      setActionLoading(v.resource_id);
      try {
          const res = await fetch(`/api/v1/sentinel/runs/${runId}/enforcement-action`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                  resource_id: v.resource_id,
                  resource_type: v.resource_type,
                  action: v.action,
                  policy_name: v.policy,
                  reason: v.reason
              })
          });
          
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Failed to execute action');
          
          setExecutedActions(prev => ({
              ...prev,
              [`${runId}-${v.resource_id}-${v.policy}-${v.action}`]: { at: new Date().toLocaleString() }
          }));
      } catch (e: any) {
          console.error(e);
          alert(`Error executing action: ${e.message}`);
      } finally {
          setActionLoading(null);
          setSelectedViolation(null);
      }
  };

  const getRunStatus = (run: any) => {
      if (run.status === 'completed') return <span className="flex items-center text-green-600 font-medium text-xs"><CheckCircle2 className="w-3 h-3 mr-1"/> Completed</span>;
      if (run.status === 'failed') return <span className="flex items-center text-red-600 font-medium text-xs"><AlertTriangle className="w-3 h-3 mr-1"/> Failed</span>;
      return <span className="flex items-center text-blue-600 font-medium text-xs"><RefreshCw className="w-3 h-3 mr-1 animate-spin"/> Running</span>;
  };

  const filteredRuns = runs.filter(r => 
      !searchQuery || 
      (r.id && r.id.toLowerCase().includes(searchQuery.toLowerCase())) || 
      (r.environment && r.environment.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (r.workspace && r.workspace.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const totalRuns = filteredRuns.length;
  const paginatedRuns = filteredRuns.slice((page - 1) * pageSize, page * pageSize);

  const activeRun = runs.find(r => r.id === activeRunId);

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Enforcement Sentinel</h1>
          <p className="text-gray-500 mt-1">Review policy violations and trigger automated enforcement runs.</p>
        </div>
        <div className="flex gap-3 bg-white p-2 rounded-lg shadow-sm border border-gray-200">
          <button
            onClick={() => triggerRun('audit')}
            disabled={triggering}
            className="flex items-center px-4 py-2 bg-gray-100 text-gray-700 border border-gray-300 rounded-md hover:bg-gray-200 disabled:opacity-50 text-sm font-medium"
          >
            {triggering ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Search className="w-4 h-4 mr-2" />}
            Run Audit
          </button>
          <button
            onClick={() => setShowConfirmModal(true)}
            disabled={triggering}
            className="flex items-center px-4 py-2 bg-primary text-white rounded-md hover:opacity-90 disabled:opacity-50 text-sm font-medium shadow-sm"
          >
            {triggering ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <AlertTriangle className="w-4 h-4 mr-2" />}
            Execute Enforcement
          </button>
        </div>
      </div>

      {/* Previous Runs Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 border-b border-gray-100">
            <div>
                <h3 className="text-lg font-semibold text-gray-900">Run History</h3>
                <p className="text-sm text-gray-500">View previous enforcement audits and findings.</p>
            </div>
            <div className="relative w-full md:w-64">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-500" />
                <input
                    type="text"
                    placeholder="Search runs..."
                    value={searchQuery}
                    onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
                    className="flex h-9 w-full rounded-md border border-gray-300 bg-white pl-9 pr-3 py-1 text-sm shadow-sm transition-colors focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
                />
            </div>
        </div>
        
        <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
                <thead className="bg-gray-50 text-gray-900 font-medium border-b border-gray-200">
                    <tr>
                        <th className="p-3 pl-5">Run Date</th>
                        <th className="p-3">Mode</th>
                        <th className="p-3">Status</th>
                        <th className="p-3">Violations</th>
                        <th className="p-3">Workspace</th>
                        <th className="p-3 text-right"></th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                    {loading && runs.length === 0 ? (
                        <tr>
                            <td colSpan={6} className="p-8 text-center text-gray-500">
                                <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-gray-400" />
                                Loading...
                            </td>
                        </tr>
                    ) : paginatedRuns.length === 0 ? (
                        <tr>
                            <td colSpan={6} className="p-8 text-center text-gray-500">
                                No Sentinel runs found. Trigger an audit to get started.
                            </td>
                        </tr>
                    ) : (
                        paginatedRuns.map(run => {
                            const vCount = run.results?.total_violations || 0;
                            const mode = run.mode === 'enforce' ? 'Enforcement' : 'Audit Only';

                            return (
                                <tr key={run.id} className="hover:bg-gray-50 transition-colors cursor-pointer group" onClick={() => { setActiveRunId(run.id); setActiveTab('all'); }}>
                                    <td className="p-3 pl-5 font-medium text-gray-900">
                                        {new Date(run.started_at).toLocaleString()}
                                    </td>
                                    <td className="p-3">
                                        <span className={`px-2 py-1 rounded text-xs font-medium ${mode === 'Enforcement' ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-800'}`}>
                                            {mode}
                                        </span>
                                    </td>
                                    <td className="p-3">
                                        {getRunStatus(run)}
                                    </td>
                                    <td className="p-3 font-medium text-gray-600">
                                        {vCount > 0 ? (
                                            <span className="text-red-600 font-bold">{vCount}</span>
                                        ) : (
                                            <span className="text-green-600">0</span>
                                        )}
                                    </td>
                                    <td className="p-3 text-gray-500">
                                        {run.workspace || 'ws-enterprise-prod'} <span className="text-xs ml-1 px-1.5 py-0.5 bg-gray-100 border border-gray-200 rounded-md">{run.environment || 'prod'}</span>
                                    </td>
                                    <td className="p-3 text-right">
                                        <button className="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50 h-8 px-3 text-gray-500 group-hover:text-gray-900 group-hover:bg-gray-200">
                                            View Report <ArrowRight className="w-4 h-4 ml-2" />
                                        </button>
                                    </td>
                                </tr>
                            );
                        })
                    )}
                </tbody>
            </table>
        </div>
        
        {/* Pagination Controls */}
        {totalRuns > 0 && (
            <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100 bg-gray-50">
                <div className="text-xs text-gray-500">
                    Showing <span className="font-medium">{(page - 1) * pageSize + 1}</span> to <span className="font-medium">{Math.min(page * pageSize, totalRuns)}</span> of <span className="font-medium">{totalRuns}</span> runs
                </div>
                <div className="flex gap-2">
                    <button 
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page === 1}
                        className="inline-flex items-center justify-center rounded-md text-xs font-medium border border-gray-300 bg-white h-7 px-2 hover:bg-gray-50 disabled:opacity-50"
                    >
                        <ChevronLeft className="w-3 h-3 mr-1" /> Prev
                    </button>
                    <button 
                        onClick={() => setPage(p => Math.min(Math.ceil(totalRuns / pageSize), p + 1))}
                        disabled={page >= Math.ceil(totalRuns / pageSize)}
                        className="inline-flex items-center justify-center rounded-md text-xs font-medium border border-gray-300 bg-white h-7 px-2 hover:bg-gray-50 disabled:opacity-50"
                    >
                        Next <ChevronRight className="w-3 h-3 ml-1" />
                    </button>
                </div>
            </div>
        )}
      </div>

      {/* Modal for run details */}
      {activeRun && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-in fade-in">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-[95vw] xl:max-w-[1600px] h-[95vh] flex flex-col overflow-hidden animate-in slide-in-from-bottom-4">
                  {/* Modal Header */}
                  <div className="flex items-center justify-between p-4 md:p-6 border-b border-gray-100 shrink-0">
                      <div>
                          <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
                              <ShieldAlert className="w-5 h-5 text-primary" />
                              Sentinel Run Report
                          </h2>
                          <p className="text-sm text-gray-500 mt-1">
                              {new Date(activeRun.started_at).toLocaleString()} • {activeRun.workspace} ({activeRun.environment}) • Mode: <span className="capitalize font-medium">{activeRun.mode}</span>
                          </p>
                      </div>
                      <button onClick={() => setActiveRunId(null)} className="p-2 rounded-full hover:bg-gray-100 transition-colors">
                          <X className="w-6 h-6 text-gray-500" />
                      </button>
                  </div>

                  {(() => {
                      const violations: any[] = activeRun.results?.violations || [];
                      const assetsScanned = activeRun.results?.total_scanned ?? '—';
                      const vCount = activeRun.results?.total_violations ?? violations.length;

                      // Group violations by policy
                      const violationsByPolicy = violations.reduce((acc: any, v: any) => {
                          if (!acc[v.policy]) acc[v.policy] = [];
                          acc[v.policy].push(v);
                          return acc;
                      }, {});

                      const policyGroups = Object.keys(violationsByPolicy).sort();
                      
                      // Sort violations by severity (highest first)
                      const severityOrder: Record<string, number> = { 'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'NONE': 0 };
                      const sortViolations = (vList: any[]) => [...vList].sort((a, b) => {
                          const sevA = severityOrder[a.severity] || 0;
                          const sevB = severityOrder[b.severity] || 0;
                          return sevB - sevA;
                      });

                      const activeViolations = sortViolations(activeTab === 'all' ? violations : (violationsByPolicy[activeTab] || []));

                      return (
                          <div className="flex-1 overflow-y-auto bg-gray-50/50 p-4 md:p-6 flex flex-col gap-6">
                              {activeRun.status === 'failed' ? (
                                  <div className="flex-1 flex flex-col items-center justify-center py-20 text-center">
                                      <AlertTriangle className="w-16 h-16 text-red-500 mb-6" />
                                      <h3 className="text-xl font-semibold text-gray-900 mb-2">
                                          Sentinel Run Failed
                                      </h3>
                                      <p className="text-red-600 font-mono text-sm bg-red-50 p-4 rounded-md border border-red-100 max-w-2xl text-left overflow-auto">
                                          {activeRun.error || 'An unexpected error occurred during the sentinel run.'}
                                      </p>
                                  </div>
                              ) : activeRun.status === 'running' ? (
                                  <div className="flex-1 flex flex-col items-center justify-center py-20 text-center">
                                      <RefreshCw className="w-16 h-16 text-primary animate-spin mb-6" />
                                      <h3 className="text-xl font-semibold text-gray-900 mb-2">
                                          Evaluating Resources...
                                      </h3>
                                      <p className="text-gray-500 max-w-md">
                                          The Sentinel is actively scanning the workspace and evaluating Open Policy Agent policies. This process can take a few moments.
                                      </p>
                                  </div>
                              ) : (
                                  <>
                                      {/* High level info cards */}
                                      <div className="flex flex-col gap-4">
                                          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                              <div className="bg-white rounded-lg p-5 shadow-sm border border-gray-200">
                                                  <div className="flex items-center text-sm font-medium text-gray-500 mb-2">
                                                      <FileStack className="w-4 h-4 mr-2" /> Assets Scanned
                                                  </div>
                                                  <div className="text-3xl font-bold text-gray-900">{assetsScanned}</div>
                                              </div>
                                              <div className="bg-white rounded-lg p-5 shadow-sm border border-gray-200">
                                                  <div className="flex items-center text-sm font-medium text-gray-500 mb-2">
                                                      <ShieldCheck className="w-4 h-4 mr-2" /> Checks Passed
                                                  </div>
                                                  <div className="text-3xl font-bold text-gray-900">{assetsScanned !== '—' ? Math.max(0, assetsScanned - vCount) : '—'}</div>
                                              </div>
                                              <div className="bg-white rounded-lg p-5 shadow-sm border border-gray-200">
                                                  <div className="flex items-center text-sm font-medium text-gray-500 mb-2">
                                                      <ListChecks className="w-4 h-4 mr-2" /> Policies Matched
                                                  </div>
                                                  <div className="text-3xl font-bold text-gray-900">{policyGroups.length}</div>
                                              </div>
                                              <div className={`rounded-lg p-5 shadow-sm border ${vCount > 0 ? 'bg-red-50/50 border-red-200' : 'bg-green-50/50 border-green-200'}`}>
                                                  <div className="flex items-center text-sm font-medium text-gray-500 mb-2">
                                                      <AlertTriangle className={`w-4 h-4 mr-2 ${vCount > 0 ? 'text-red-500' : 'text-green-500'}`} /> Total Violations
                                                  </div>
                                                  <div className={`text-3xl font-bold ${vCount > 0 ? 'text-red-600' : 'text-green-600'}`}>{vCount}</div>
                                              </div>
                                          </div>
                                          
                                          {/* Severity Breakdown */}
                                          {vCount > 0 && (
                                              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                                  {['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(sev => {
                                                      const count = violations.filter((v: any) => v.severity === sev).length;
                                                      const colors = sev === 'CRITICAL' && count > 0 ? 'bg-red-50/30 border-red-100' :
                                                                     sev === 'HIGH' && count > 0 ? 'bg-orange-50/30 border-orange-100' :
                                                                     sev === 'MEDIUM' && count > 0 ? 'bg-yellow-50/30 border-yellow-100' :
                                                                     'bg-white border-gray-200 opacity-60';
                                                      const textColors = sev === 'CRITICAL' && count > 0 ? 'text-red-600' :
                                                                         sev === 'HIGH' && count > 0 ? 'text-orange-600' :
                                                                         sev === 'MEDIUM' && count > 0 ? 'text-yellow-600' :
                                                                         'text-gray-400';
                                                      return (
                                                          <div key={sev} className={`rounded-lg shadow-sm border p-4 flex flex-col items-center justify-center gap-1 ${colors}`}>
                                                              <div className="flex items-center text-xs font-semibold text-gray-500 uppercase tracking-wider">
                                                                  {sev}
                                                              </div>
                                                              <div className={`text-2xl font-bold ${textColors}`}>{count}</div>
                                                          </div>
                                                      );
                                                  })}
                                              </div>
                                          )}
                                      </div>

                                      {/* Detailed Report Section */}
                                      <div className="bg-white border border-gray-200 rounded-lg shadow-sm flex flex-col overflow-hidden flex-1 min-h-[400px]">
                                          {/* Tabs */}
                                          <div className="flex overflow-x-auto border-b border-gray-200 bg-gray-50/80 p-3 gap-2 hide-scrollbar shrink-0">
                                              <button
                                                  onClick={() => setActiveTab('all')}
                                                  className={`px-4 py-2 text-sm font-medium rounded-md whitespace-nowrap transition-colors ${
                                                      activeTab === 'all' 
                                                      ? 'bg-white text-primary shadow-sm ring-1 ring-gray-200' 
                                                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-200'
                                                  }`}
                                              >
                                                  All Violations ({violations.length})
                                              </button>
                                              {policyGroups.map(policy => (
                                                  <button
                                                      key={policy}
                                                      onClick={() => setActiveTab(policy)}
                                                      className={`px-4 py-2 text-sm font-medium rounded-md whitespace-nowrap transition-colors ${
                                                          activeTab === policy 
                                                          ? 'bg-white text-primary shadow-sm ring-1 ring-gray-200' 
                                                          : 'text-gray-600 hover:text-gray-900 hover:bg-gray-200'
                                                      }`}
                                                  >
                                                      {policy.replace(/_/g, ' ')} ({violationsByPolicy[policy].length})
                                                  </button>
                                              ))}
                                          </div>

                                          {/* Tab Content */}
                                          <div className="p-0 overflow-y-auto flex-1">
                                              {activeViolations.length === 0 ? (
                                                  <div className="flex flex-col items-center justify-center h-full p-16 text-center">
                                                      <CheckCircle2 className="w-16 h-16 text-green-400 mb-4" />
                                                      <h3 className="text-xl font-medium text-gray-900">No violations found</h3>
                                                      <p className="text-gray-500 mt-2 max-w-sm">
                                                          {activeTab === 'all' 
                                                              ? 'All scanned resources are compliant with current policies.'
                                                              : `No resources violated the ${activeTab.replace(/_/g, ' ')} policy group.`}
                                                      </p>
                                                  </div>
                                              ) : (
                                                  <table className="w-full text-sm">
                                                      <thead className="bg-white text-gray-500 font-medium border-b border-gray-200 sticky top-0 z-10 shadow-sm">
                                                          <tr>
                                                              <th className="p-4 pl-6 text-left">Resource</th>
                                                              {activeTab === 'all' && <th className="p-4 text-left">Policy</th>}
                                                              <th className="p-4 text-left">Severity</th>
                                                              <th className="p-4 text-left">Action</th>
                                                              <th className="p-4 text-left w-1/3">Reason</th>
                                                              {activeRun.mode === 'audit' && (
                                                                  <th className="p-4 pr-6 text-right">Controls</th>
                                                              )}
                                                          </tr>
                                                      </thead>
                                                      <tbody className="divide-y divide-gray-100">
                                                          {activeViolations.map((v: any, idx: number) => (
                                                              <tr key={idx} className="hover:bg-gray-50 transition-colors">
                                                                  <td className="p-4 pl-6 font-mono text-xs text-gray-900 align-top">
                                                                      <div className="flex flex-col gap-1">
                                                                          <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider font-sans bg-gray-100 px-1.5 py-0.5 rounded w-max inline-block">
                                                                              {v.resource_type}
                                                                          </span>
                                                                          <span className="break-all">{v.resource_id}</span>
                                                                      </div>
                                                                  </td>
                                                                  {activeTab === 'all' && <td className="p-4 text-gray-700 align-top font-medium">{v.policy.replace(/_/g, ' ')}</td>}
                                                                  <td className="p-4 align-top">
                                                                      <span className={`text-[10px] uppercase font-bold px-2.5 py-1 rounded-full whitespace-nowrap ${
                                                                          v.severity === 'CRITICAL' ? 'bg-red-100 text-red-800 border border-red-200' :
                                                                          v.severity === 'HIGH' ? 'bg-orange-100 text-orange-800 border border-orange-200' :
                                                                          v.severity === 'MEDIUM' ? 'bg-yellow-100 text-yellow-800 border border-yellow-200' :
                                                                          'bg-gray-100 text-gray-800 border border-gray-200'
                                                                      }`}>
                                                                          {v.severity}
                                                                      </span>
                                                                  </td>
                                                                  <td className="p-4 align-top">
                                                                      <span className={`font-mono text-xs font-bold px-2 py-1 rounded ${
                                                                           v.action === 'KILL' ? 'bg-red-50 text-red-700' :
                                                                           v.action === 'WARN' ? 'bg-yellow-50 text-yellow-700' :
                                                                           'bg-gray-100 text-gray-700'
                                                                      }`}>{v.action}</span>
                                                                  </td>
                                                                  <td className="p-4 text-sm text-gray-600 break-words leading-relaxed align-top">
                                                                      {formatReason(v)}
                                                                  </td>
                                                                  {activeRun.mode === 'audit' && (
                                                                      <td className="p-4 pr-6 text-right align-top">
                                                                          {(() => {
                                                                              const execKey = `${activeRun.id}-${v.resource_id}-${v.policy}-${v.action}`;
                                                                              const executed = executedActions[execKey];
                                                                              if (executed) {
                                                                                  return (
                                                                                      <div className="flex flex-col items-end mt-1">
                                                                                          <span className="text-xs font-semibold text-green-600 flex items-center">
                                                                                              <CheckCircle2 className="w-3 h-3 mr-1" /> Executed
                                                                                          </span>
                                                                                          <span className="text-[10px] text-gray-500 mt-0.5">by you on {executed.at}</span>
                                                                                      </div>
                                                                                  );
                                                                              }
                                                                              return ['KILL', 'WARN', 'CERTIFY', 'UNCERTIFY'].includes(v.action) && (
                                                                                  <button 
                                                                                      className="inline-flex items-center justify-center rounded-md text-xs font-medium border border-blue-200 text-blue-600 hover:bg-blue-50 h-7 px-2 mt-0.5"
                                                                                      onClick={() => setSelectedViolation(v)}
                                                                                  >
                                                                                      Review and Act
                                                                                  </button>
                                                                              );
                                                                          })()}
                                                                      </td>
                                                                  )}
                                                              </tr>
                                                          ))}
                                                      </tbody>
                                                  </table>
                                              )}
                                          </div>
                                      </div>
                                  </>
                              )}
                          </div>
                      );
                  })()}
              </div>
          </div>
      )}

      {showConfirmModal && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden animate-in zoom-in-95 border-t-4 border-red-500">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-4">
                  <div className="bg-red-100 p-2 rounded-full shrink-0">
                      <AlertTriangle className="w-6 h-6 text-red-600" />
                  </div>
                  <h3 className="text-xl font-bold text-gray-900">Execute Enforcement?</h3>
              </div>
              <p className="text-gray-600 mb-6">
                Are you sure you want to execute enforcement? This will perform destructive actions (like <strong className="text-red-600 font-mono">KILL</strong> or <strong className="text-orange-600 font-mono">WARN</strong>) on non-compliant resources based on the active policies.
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowConfirmModal(false)}
                  className="px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => triggerRun('enforce')}
                  className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 font-medium shadow-sm transition-colors"
                >
                  Confirm Execution
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Review and Act Modal */}
      {selectedViolation && activeRun && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-in fade-in">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden animate-in zoom-in-95">
                  <div className="flex items-center justify-between p-4 border-b border-gray-100 bg-white shrink-0">
                      <h3 className="text-lg font-semibold text-gray-900">Review and Act: {selectedViolation.resource_id}</h3>
                      <button onClick={() => setSelectedViolation(null)} className="p-2 rounded-full hover:bg-gray-100 transition-colors">
                          <X className="w-5 h-5 text-gray-500" />
                      </button>
                  </div>
                  <div className="p-6 overflow-y-auto flex-1 space-y-6">
                      <div className="grid grid-cols-2 gap-4 text-sm bg-gray-50 p-4 rounded-lg border border-gray-100">
                          <div><span className="font-semibold text-gray-500 block mb-1">Resource Type</span> {selectedViolation.resource_type}</div>
                          <div><span className="font-semibold text-gray-500 block mb-1">Policy</span> {selectedViolation.policy}</div>
                          <div>
                              <span className="font-semibold text-gray-500 block mb-1">Severity</span>
                              <span className={`text-[10px] uppercase font-bold px-2 py-1 rounded-full ${
                                  selectedViolation.severity === 'CRITICAL' ? 'bg-red-100 text-red-800 border border-red-200' :
                                  selectedViolation.severity === 'HIGH' ? 'bg-orange-100 text-orange-800 border border-orange-200' :
                                  selectedViolation.severity === 'MEDIUM' ? 'bg-yellow-100 text-yellow-800 border border-yellow-200' :
                                  'bg-gray-100 text-gray-800 border border-gray-200'
                              }`}>
                                  {selectedViolation.severity}
                              </span>
                          </div>
                          <div><span className="font-semibold text-gray-500 block mb-1">Action</span> <span className="font-mono font-bold text-gray-700">{selectedViolation.action}</span></div>
                          <div className="col-span-2"><span className="font-semibold text-gray-500 block mb-1">Reason</span> <div className="mt-1 text-gray-700 leading-relaxed">{formatReason(selectedViolation)}</div></div>
                      </div>
                      
                      <div>
                          <h4 className="text-sm font-semibold text-gray-900 mb-2">Full Violation Context</h4>
                          <pre className="bg-gray-900 p-4 rounded-lg border border-gray-700 text-xs font-mono text-green-400 overflow-x-auto whitespace-pre-wrap break-words shadow-inner">
                              {JSON.stringify(selectedViolation, null, 2)}
                          </pre>
                      </div>
                  </div>
                  <div className="p-4 border-t border-gray-100 bg-gray-50 flex justify-end gap-3 shrink-0">
                      <button 
                        className="px-4 py-2 bg-gray-100 text-gray-700 border border-gray-300 rounded-md hover:bg-gray-200 text-sm font-medium"
                        onClick={() => setSelectedViolation(null)}
                      >
                        Cancel
                      </button>
                      <button 
                          disabled={actionLoading === selectedViolation.resource_id}
                          onClick={() => handleExecuteAction(activeRun.id, selectedViolation)}
                          className="flex items-center px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-md text-sm font-medium shadow-sm disabled:opacity-50"
                      >
                          {actionLoading === selectedViolation.resource_id ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : null}
                          Execute Action
                      </button>
                  </div>
              </div>
          </div>
      )}
    </div>
  );
}