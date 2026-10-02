import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { isOperator, isOrgAdmin, useAuth } from "./auth";
import Account from "./pages/Account";
import About from "./pages/About";
import ApiDocs from "./pages/ApiDocs";
import Analytics from "./pages/Analytics";
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
import OperatorScores from "./pages/OperatorScores";
import PaymentResult from "./pages/PaymentResult";
import Signup from "./pages/Signup";
import KpiSettings from "./pages/KpiSettings";
import Profile from "./pages/Profile";

export default function App() {
  const { session, loading } = useAuth();

  if (loading) {
    return <div className="p-10 text-center text-slate-500">در حال بارگذاری…</div>;
  }
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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }

  const operator = isOperator(session.role);
  const orgAdmin = isOrgAdmin(session.role);

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/calls" element={<Calls />} />
        <Route path="/calls/:callId" element={<CallDetailPage />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/assistant" element={<Assistant />} />
        <Route path="/operator-scores" element={<OperatorScores />} />
        <Route path="/profile" element={<Profile />} />
        {operator ? null : <Route path="/account" element={<Account />} />}
        {orgAdmin ? <Route path="/checkout" element={<Checkout />} /> : null}
        {orgAdmin ? <Route path="/kpi-settings" element={<KpiSettings />} /> : null}
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
