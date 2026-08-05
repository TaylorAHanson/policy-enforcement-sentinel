import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import Allowlist from "./pages/Allowlist";
import PolicyEditor from "./pages/PolicyEditor";
import Presentation from "./pages/Presentation";
import QuickReference from "./pages/QuickReference";
import ReleaseNotes from "./pages/ReleaseNotes";
import SentinelDashboard from "./pages/SentinelDashboard";
import SettingsPage from "./pages/Settings";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Layout renders an <Outlet/>, so page state survives navigation
            between siblings and the enforcement banner is mounted once. */}
        <Route element={<Layout />}>
          <Route index element={<SentinelDashboard />} />
          <Route path="/policies" element={<PolicyEditor />} />
          <Route path="/allowlist" element={<Allowlist />} />
          <Route path="/reference" element={<QuickReference />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/releases" element={<ReleaseNotes />} />
          <Route path="/presentation" element={<Presentation />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
