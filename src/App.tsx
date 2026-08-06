import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import Allowlist from "./pages/Allowlist";
import PolicyDashboard from "./pages/PolicyDashboard";
import PolicyEditor from "./pages/PolicyEditor";
import Presentation from "./pages/Presentation";
import QuickReference from "./pages/QuickReference";
import ReleaseNotes from "./pages/ReleaseNotes";
import SentinelDashboard from "./pages/SentinelDashboard";
import SettingsPage from "./pages/Settings";
import Testing from "./pages/Testing";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Layout renders an <Outlet/>, so page state survives navigation
            between siblings and the enforcement banner is mounted once. */}
        <Route element={<Layout />}>
          <Route index element={<SentinelDashboard />} />
          {/* The list is the page; the editor is somewhere you go from it.
              Putting the policy in the URL also makes an open policy something
              you can link to, which the in-memory selection never was. */}
          <Route path="/policies" element={<PolicyDashboard />} />
          <Route path="/policies/:policyName" element={<PolicyEditor />} />
          <Route path="/allowlist" element={<Allowlist />} />
          <Route path="/testing" element={<Testing />} />
          <Route path="/reference" element={<QuickReference />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/releases" element={<ReleaseNotes />} />
          <Route path="/presentation" element={<Presentation />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
