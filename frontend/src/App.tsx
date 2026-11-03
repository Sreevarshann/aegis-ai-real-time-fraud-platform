import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import DataIntelligence from "./pages/DataIntelligence";
import InvestigationDetail from "./pages/InvestigationDetail";
import Investigations from "./pages/Investigations";
import Login from "./pages/Login";
import ModelIntelligence from "./pages/ModelIntelligence";
import Operations from "./pages/Operations";
import Overview from "./pages/Overview";
import Transactions from "./pages/Transactions";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="grid h-full place-items-center text-mist-500"><Spinner className="h-6 w-6" /></div>;
  }
  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/transactions" element={<Transactions />} />
        <Route path="/investigations" element={<Investigations />} />
        <Route path="/investigations/:id" element={<InvestigationDetail />} />
        <Route path="/data" element={<DataIntelligence />} />
        <Route path="/models" element={<ModelIntelligence />} />
        <Route path="/operations" element={<Operations />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
