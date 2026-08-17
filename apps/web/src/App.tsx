import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { GuidePage } from "./pages/GuidePage";
import { ChatPage } from "./pages/ChatPage";
import { TicketsPage } from "./pages/TicketsPage";
import { ReturnsPage } from "./pages/ReturnsPage";
import { MetricsPage } from "./pages/MetricsPage";
import { TracesPage } from "./pages/TracesPage";
import { ObservabilityPage } from "./pages/ObservabilityPage";
import { MemoryInspectorPage } from "./pages/MemoryInspectorPage";
import type { Role } from "./types/api";

export type PageId =
  | "guide"
  | "chat"
  | "tickets"
  | "returns"
  | "metrics"
  | "traces"
  | "observability"
  | "memory"
  | "rules";

export default function App() {
  const [page, setPage] = useState<PageId>("guide");
  const [role, setRole] = useState<Role>("consumer");
  const [userId, setUserId] = useState("user-001");
  const [chatPrefill, setChatPrefill] = useState<{ message: string; orderId?: string } | undefined>();

  function navigate(p: PageId) {
    setPage(p);
    setChatPrefill(undefined);
  }

  function startDemo(message: string, orderId?: string) {
    setChatPrefill({ message, orderId });
    setPage("chat");
  }

  return (
    <div className="app-layout">
      <Sidebar
        page={page}
        role={role}
        userId={userId}
        onNavigate={navigate}
        onRoleChange={setRole}
        onUserIdChange={setUserId}
      />
      <div className="main-content">
        {page === "guide" && <GuidePage onDemo={startDemo} />}
        {page === "chat" && <ChatPage role={role} userId={userId} prefill={chatPrefill} onNavigate={navigate} />}
        {page === "tickets" && <TicketsPage role={role} userId={userId} />}
        {page === "returns" && <ReturnsPage role={role} userId={userId} />}
        {page === "metrics" && <MetricsPage />}
        {page === "traces" && <TracesPage />}
        {page === "observability" && <ObservabilityPage />}
        {page === "memory" && <MemoryInspectorPage />}
        {page === "rules" && <RulesPage />}
      </div>
    </div>
  );
}

function RulesPage() {
  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">规则体系</h1>
        <p className="page-subtitle">Intent Catalog、Skill Manifest 与 Tool 权限</p>
      </div>
      <div className="card">
        <h3 className="card-title">Intent Catalog（6 意图）</h3>
        <div className="table-container">
          <table>
            <thead>
              <tr><th>Intent</th><th>风险等级</th><th>Signal</th><th>Tool 权限</th></tr>
            </thead>
            <tbody>
              <tr><td>query_order_logistics</td><td><span className="badge badge-success">low</span></td><td>订单/物流</td><td>query_order_logistics</td></tr>
              <tr><td>consult_return_policy</td><td><span className="badge badge-info">medium</span></td><td>退换货政策</td><td>search_policy</td></tr>
              <tr><td>submit_return_application</td><td><span className="badge badge-danger">high</span></td><td>提交退货</td><td>check_eligibility + submit_return</td></tr>
              <tr><td>risk_handoff</td><td><span className="badge badge-danger">high</span></td><td>人工接管</td><td>create_ticket</td></tr>
              <tr><td>general_qa</td><td><span className="badge badge-info">medium</span></td><td>通用问答</td><td>search_policy</td></tr>
              <tr><td>unsupported</td><td><span className="badge badge-warning">n/a</span></td><td>未支持</td><td>—</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
