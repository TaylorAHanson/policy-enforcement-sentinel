import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { Shield, Code, BookOpen, ShieldCheck } from 'lucide-react';
import SentinelDashboard from './pages/SentinelDashboard';
import PolicyEditor from './pages/PolicyEditor';
import QuickReference from './pages/QuickReference';
import Allowlist from './pages/Allowlist';

function Layout({ children, branding }: { children: React.ReactNode, branding: any }) {
  return (
    <div className="flex h-screen bg-[#0b0f15] text-slate-200 font-sans">
      <aside className="w-64 bg-[#11151c] border-r border-slate-800 flex flex-col">
        <div className="h-16 flex items-center px-6 border-b border-slate-800 shrink-0">
          {branding?.logo_url ? (
            <img src={branding.logo_url} alt="Logo" className="h-8 max-w-[80px] object-contain mr-3 shrink-0 brightness-0 invert" />
          ) : (
            <Shield className="w-6 h-6 text-blue-500 mr-2 shrink-0" />
          )}
          <span className="font-semibold text-slate-100 text-sm leading-tight line-clamp-2" title={branding?.name}>{branding?.name || 'Sentinel'}</span>
        </div>
        <nav className="p-3 space-y-1 flex-1 overflow-y-auto">
          <NavLink
            to="/"
            className={({ isActive }) =>
              `flex items-center px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                isActive ? 'bg-[#8acaff14] text-[#8acaff]' : 'text-[#e8ecf0] hover:bg-[#8acaff14] hover:text-[#8acaff]'
              }`
            }
          >
            <Shield className="w-4 h-4 mr-3" />
            Dashboard
          </NavLink>
          <NavLink
            to="/policies"
            className={({ isActive }) =>
              `flex items-center px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                isActive ? 'bg-[#8acaff14] text-[#8acaff]' : 'text-[#e8ecf0] hover:bg-[#8acaff14] hover:text-[#8acaff]'
              }`
            }
          >
            <Code className="w-4 h-4 mr-3" />
            Policy Editor
          </NavLink>
          <NavLink
            to="/allowlist"
            className={({ isActive }) =>
              `flex items-center px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                isActive ? 'bg-[#8acaff14] text-[#8acaff]' : 'text-[#e8ecf0] hover:bg-[#8acaff14] hover:text-[#8acaff]'
              }`
            }
          >
            <ShieldCheck className="w-4 h-4 mr-3" />
            Allowlist
          </NavLink>
          <NavLink
            to="/reference"
            className={({ isActive }) =>
              `flex items-center px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                isActive ? 'bg-[#8acaff14] text-[#8acaff]' : 'text-[#e8ecf0] hover:bg-[#8acaff14] hover:text-[#8acaff]'
              }`
            }
          >
            <BookOpen className="w-4 h-4 mr-3" />
            Quick Reference
          </NavLink>
        </nav>
      </aside>
      <main className="flex-1 overflow-auto bg-[#0b0f15] p-8">
        {children}
      </main>
    </div>
  );
}

export default function App() {
  const [branding, setBranding] = useState<any>({});

  useEffect(() => {
    fetch('/api/v1/branding')
      .then(res => res.json())
      .then(data => {
        setBranding(data);
        if (data.primary_color) {
          document.documentElement.style.setProperty('--brand-primary', data.primary_color);
        }
        if (data.name) {
          document.title = data.name;
        }
      })
      .catch(console.error);
  }, []);

  return (
    <BrowserRouter>
      <Layout branding={branding}>
        <Routes>
          <Route path="/" element={<SentinelDashboard />} />
          <Route path="/policies" element={<PolicyEditor />} />
          <Route path="/allowlist" element={<Allowlist />} />
          <Route path="/reference" element={<QuickReference />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}