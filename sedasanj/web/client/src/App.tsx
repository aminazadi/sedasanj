import { useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import { isOperator, isOrgAdmin, useAuth } from "./auth";
import Account from "./pages/Account";
import AccountSettings from "./pages/AccountSettings";
import About from "./pages/About";
import ApiDocs from "./pages/ApiDocs";
import CallDetailPage from "./pages/CallDetail";
import Calls from "./pages/Calls";
import Contact from "./pages/Contact";
import Checkout from "./pages/Checkout";
import Install from "./pages/Install";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Legal from "./pages/Legal";
import Overview from "./pages/Overview";
import Tasks from "./pages/Tasks";
import Assistant from "./pages/Assistant";
import ScheduledReports from "./pages/ScheduledReports";
import OperatorScores from "./pages/OperatorScores";
import PaymentResult from "./pages/PaymentResult";
import PlanSelection from "./pages/PlanSelection";
import Signup from "./pages/Signup";
import Profile from "./pages/Profile";
import QuickDemo from "./pages/QuickDemo";
import DemoRecorder from "./pages/DemoRecorder";
import { RouteLoadingOverlay } from "./components/BrandLoader";

export default function App() {
  const { session, loading } = useAuth();
  const location = useLocation();
  const [initialLoaderComplete, setInitialLoaderComplete] = useState(false);

  if (location.pathname === "/demo/record") return <DemoRecorder />;
  if (loading || !initialLoaderComplete) {
    return <RouteLoadingOverlay persist={loading} onComplete={() => setInitialLoaderComplete(true)} />;
  }
  if (location.pathname === "/quick-demo") return <QuickDemo />;
  if (!session) {
    return (
      <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/about" element={<About />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/terms" element={<Legal title="قوانین استفاده" />} />
          <Route path="/privacy" element={<Legal title="حریم خصوصی" />} />
          <Route path="/cancellation" element={<Legal title="سیاست لغو اشتراک" />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/login" element={<Login />} />
          <Route path="/quick-demo" element={<QuickDemo />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
  }

  const operator = isOperator(session.role);
  const orgAdmin = isOrgAdmin(session.role);

  if (location.pathname === "/plans" || location.pathname === "/checkout") {
    if (!orgAdmin) return <Navigate to="/" replace />;
    return location.pathname === "/plans" ? <PlanSelection /> : <Checkout />;
  }

  return (
    <Layout>
        <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/calls" element={<Calls />} />
        <Route path="/quick-demo" element={<QuickDemo />} />
        <Route path="/calls/:callId" element={<CallDetailPage />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/assistant" element={<Assistant />} />
        {orgAdmin ? <Route path="/scheduled-reports" element={<ScheduledReports />} /> : null}
        <Route path="/operator-scores" element={<OperatorScores />} />
        <Route path="/profile" element={<Profile />} />
        {operator ? null : <Route path="/account" element={<Account />} />}
        {orgAdmin ? <Route path="/account-settings" element={<AccountSettings />} /> : null}
        {orgAdmin ? <Route path="/kpi-settings" element={<Navigate to="/account-settings?tab=kpi" replace />} /> : null}
        {orgAdmin ? <Route path="/payment-result" element={<PaymentResult />} /> : null}
        {operator ? null : <Route path="/install" element={<Install />} />}
        <Route path="/about" element={<About />} />
        <Route path="/contact" element={<Contact />} />
        <Route path="/terms" element={<Legal title="قوانین استفاده" />} />
        <Route path="/privacy" element={<Legal title="حریم خصوصی" />} />
        <Route path="/cancellation" element={<Legal title="سیاست لغو اشتراک" />} />
        <Route path="/api-docs" element={<ApiDocs />} />
        <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
  );
}
