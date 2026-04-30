import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { Shield, Code, BookOpen } from 'lucide-react';
import SentinelDashboard from './pages/SentinelDashboard';
import PolicyEditor from './pages/PolicyEditor';
import QuickReference from './pages/QuickReference';

function Layout({ children, branding }: { children: React.ReactNode, branding: any }) {
  return (
    <div className="flex h-screen bg-gray-100">
      <aside className="w-64 bg-white border-r border-gray-200">
        <div className="h-16 flex items-center px-6 border-b border-gray-200 overflow-hidden">
          {branding?.logo_url ? (
            <img src={branding.logo_url} alt="Logo" className="h-8 max-w-[80px] object-contain mr-3 shrink-0" />
          ) : (
            <Shield className="w-6 h-6 text-primary mr-2 shrink-0" />
          )}
          <span className="font-bold text-gray-900 text-sm leading-tight line-clamp-2" title={branding?.name}>{branding?.name || 'Sentinel'}</span>
        </div>
        <nav className="p-4 space-y-1">
          <NavLink
            to="/"
            className={({ isActive }) =>
              `flex items-center px-3 py-2 text-sm font-medium rounded-md ${
                isActive ? 'bg-gray-100 text-primary' : 'text-gray-700 hover:bg-gray-50'
              }`
            }
          >
            <Shield className="w-5 h-5 mr-3" />
            Dashboard
          </NavLink>
          <NavLink
            to="/policies"
            className={({ isActive }) =>
              `flex items-center px-3 py-2 text-sm font-medium rounded-md ${
                isActive ? 'bg-gray-100 text-primary' : 'text-gray-700 hover:bg-gray-50'
              }`
            }
          >
            <Code className="w-5 h-5 mr-3" />
            Policy Editor
          </NavLink>
          <NavLink
            to="/reference"
            className={({ isActive }) =>
              `flex items-center px-3 py-2 text-sm font-medium rounded-md ${
                isActive ? 'bg-gray-100 text-primary' : 'text-gray-700 hover:bg-gray-50'
              }`
            }
          >
            <BookOpen className="w-5 h-5 mr-3" />
            Quick Reference
          </NavLink>
        </nav>
      </aside>
      <main className="flex-1 overflow-auto bg-gray-50 p-8">
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
          <Route path="/reference" element={<QuickReference />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
