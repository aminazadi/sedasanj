import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import Audit from "./pages/Audit";
import Commerce from "./pages/Commerce";
import CommerceSettings from "./pages/CommerceSettings";
import Installations from "./pages/Installations";
import Plans from "./pages/Plans";
import Sales from "./pages/Sales";
import Staff from "./pages/Staff";
import Subscriptions from "./pages/Subscriptions";
import Dashboard from "./pages/Dashboard";
import Jobs from "./pages/Jobs";
import Login from "./pages/Login";
import Packages from "./pages/Packages";
import Settings from "./pages/Settings";
import TenantDetailPage from "./pages/TenantDetail";
import Tenants from "./pages/Tenants";
import TenantDatabases from "./pages/TenantDatabases";

export default function App() {
  const { session, loading } = useAuth();

  if (loading) return <div className="p-10 text-center text-slate-500">در حال بارگذاری…</div>;
  if (!session) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/tenants" element={<Tenants />} />
        <Route path="/tenants/:tenantId" element={<TenantDetailPage />} />
        <Route path="/tenant-databases" element={<TenantDatabases />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/packages" element={<Packages />} />
        <Route path="/plans" element={<Plans />} />
        <Route path="/subscriptions" element={<Subscriptions />} />
        <Route path="/commerce" element={<Commerce />} />
        <Route path="/sales" element={<Sales />} />
        <Route path="/installations" element={<Installations />} />
        <Route path="/staff" element={<Staff />} />
        <Route path="/commerce-settings" element={<CommerceSettings />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
