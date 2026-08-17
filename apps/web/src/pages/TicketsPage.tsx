import { useState, useEffect } from "react";
import { listTickets, resolveTicket } from "../services/api";
import type { Role, Ticket, TicketSummary } from "../types/api";

interface Props {
  role: Role;
  userId: string;
}

export function TicketsPage({ role, userId }: Props) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [reply, setReply] = useState("");
  const [reviewReason, setReviewReason] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await listTickets({ page, page_size: 20, keyword, status }, role, userId);
      setTickets(res.tickets || []);
      setTotal(res.pagination?.total || 0);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [page]); // eslint-disable-line

  function parseSummary(t: Ticket): TicketSummary {
    if (!t.summary) return {};
    if (typeof t.summary === "string") {
      try { return JSON.parse(t.summary); } catch { return {}; }
    }
    return t.summary as TicketSummary;
  }

  async function doResolve() {
    if (!selected) return;
    try {
      await resolveTicket(selected.ticket_id, { agent_reply: reply, review_reason: reviewReason }, role, userId);
      setSelected(null);
      setReply("");
      setReviewReason("");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">工单队列</h1>
        <p className="page-subtitle">人工接管工单 · 共 {total} 条</p>
      </div>

      <div className="filters-bar">
        <div className="form-group">
          <input className="form-input" placeholder="关键词" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        </div>
        <div className="form-group">
          <select className="form-select" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">全部状态</option>
            <option value="pending">pending</option>
            <option value="resolved">resolved</option>
          </select>
        </div>
        <button className="btn btn-primary" onClick={() => { setPage(1); load(); }}>查询</button>
      </div>

      {error && <div className="error-message" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        {loading ? (
          <div className="loading"><div className="spinner" />加载中...</div>
        ) : tickets.length === 0 ? (
          <div className="empty-state">暂无工单</div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Ticket ID</th><th>订单</th><th>分类</th><th>优先级</th><th>状态</th><th>创建时间</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((t) => (
                  <tr key={t.ticket_id}>
                    <td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{t.ticket_id}</td>
                    <td>{t.order_id || "—"}</td>
                    <td><span className="badge badge-info">{t.category}</span></td>
                    <td><span className={`badge ${t.priority === "high" ? "badge-danger" : t.priority === "medium" ? "badge-warning" : "badge-default"}`}>{t.priority}</span></td>
                    <td><span className={`badge ${t.status === "resolved" ? "badge-success" : "badge-warning"}`}>{t.status}</span></td>
                    <td style={{ fontSize: 12 }}>{t.created_at}</td>
                    <td><button className="btn btn-secondary" style={{ padding: "4px 8px" }} onClick={() => setSelected(t)}>详情</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && (
        <div className="confirm-overlay" onClick={() => setSelected(null)}>
          <div className="confirm-dialog" style={{ maxWidth: 640 }} onClick={(e) => e.stopPropagation()}>
            <h3>工单详情 — {selected.ticket_id}</h3>
            <div style={{ marginBottom: 12 }}>
              <div className="context-item"><span className="label">订单</span><span className="value">{selected.order_id || "—"}</span></div>
              <div className="context-item"><span className="label">分类</span><span className="value">{selected.category}</span></div>
              <div className="context-item"><span className="label">优先级</span><span className="value">{selected.priority}</span></div>
              <div className="context-item"><span className="label">状态</span><span className="value">{selected.status}</span></div>
              <div className="context-item"><span className="label">接管原因</span><span className="value">{selected.handoff_reason || "—"}</span></div>
            </div>
            {(() => {
              const s = parseSummary(selected);
              return (
                <div style={{ marginBottom: 12, fontSize: 13 }}>
                  {s.user_request && <p><strong>用户诉求：</strong>{s.user_request}</p>}
                  {s.actions_taken && <p><strong>已执行：</strong>{s.actions_taken.join("；")}</p>}
                  {s.handoff_reason && <p><strong>接管原因：</strong>{s.handoff_reason}</p>}
                </div>
              );
            })()}
            {selected.status === "pending" && role === "agent" && (
              <>
                <div className="form-group">
                  <label className="form-label">回复内容</label>
                  <textarea className="form-textarea" value={reply} onChange={(e) => setReply(e.target.value)} placeholder="输入客服回复..." />
                </div>
                <div className="form-group">
                  <label className="form-label">处理说明</label>
                  <input className="form-input" value={reviewReason} onChange={(e) => setReviewReason(e.target.value)} placeholder="处理理由" />
                </div>
                <div className="actions">
                  <button className="btn btn-secondary" onClick={() => setSelected(null)}>取消</button>
                  <button className="btn btn-primary" onClick={doResolve}>解决工单</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
