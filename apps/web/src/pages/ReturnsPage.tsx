import { useState, useEffect } from "react";
import { listReturnApplications, reviewReturnApplication } from "../services/api";
import type { Role, ReturnApplication } from "../types/api";

interface Props { role: Role; userId: string; }

export function ReturnsPage({ role, userId }: Props) {
  const [apps, setApps] = useState<ReturnApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<ReturnApplication | null>(null);
  const [decision, setDecision] = useState<"approve" | "reject">("approve");
  const [reviewReason, setReviewReason] = useState("");

  async function load() {
    setLoading(true);
    try {
      const res = await listReturnApplications({ page, page_size: 20, keyword, status }, role, userId);
      setApps(res.applications || []);
      setTotal(res.pagination?.total || 0);
    } catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [page]); // eslint-disable-line

  async function doReview() {
    if (!selected) return;
    try {
      await reviewReturnApplication(selected.application_id, { decision, review_reason: reviewReason }, role, userId);
      setSelected(null);
      setReviewReason("");
      load();
    } catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">退货审核</h1>
        <p className="page-subtitle">退货申请审核队列 · 共 {total} 条</p>
      </div>
      <div className="filters-bar">
        <div className="form-group"><input className="form-input" placeholder="关键词" value={keyword} onChange={(e) => setKeyword(e.target.value)} /></div>
        <div className="form-group">
          <select className="form-select" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">全部状态</option>
            <option value="pending_review">pending_review</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
          </select>
        </div>
        <button className="btn btn-primary" onClick={() => { setPage(1); load(); }}>查询</button>
      </div>
      {error && <div className="error-message" style={{ marginBottom: 16 }}>{error}</div>}
      <div className="card">
        {loading ? <div className="loading"><div className="spinner" />加载中...</div>
        : apps.length === 0 ? <div className="empty-state">暂无退货申请</div>
        : (
          <div className="table-container">
            <table>
              <thead><tr><th>Application ID</th><th>订单</th><th>原因</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead>
              <tbody>
                {apps.map((a) => (
                  <tr key={a.application_id}>
                    <td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{a.application_id}</td>
                    <td>{a.order_id}</td>
                    <td>{a.reason}</td>
                    <td><span className={`badge ${a.status === "approved" ? "badge-success" : a.status === "rejected" ? "badge-danger" : "badge-warning"}`}>{a.status}</span></td>
                    <td style={{ fontSize: 12 }}>{a.submitted_at}</td>
                    <td><button className="btn btn-secondary" style={{ padding: "4px 8px" }} onClick={() => setSelected(a)}>详情</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {selected && (
        <div className="confirm-overlay" onClick={() => setSelected(null)}>
          <div className="confirm-dialog" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
            <h3>退货申请 — {selected.application_id}</h3>
            <div style={{ marginBottom: 12 }}>
              <div className="context-item"><span className="label">订单</span><span className="value">{selected.order_id}</span></div>
              <div className="context-item"><span className="label">原因</span><span className="value">{selected.reason}</span></div>
              <div className="context-item"><span className="label">状态</span><span className="value">{selected.status}</span></div>
              <div className="context-item"><span className="label">提交时间</span><span className="value">{selected.submitted_at}</span></div>
              {selected.reviewed_at && <div className="context-item"><span className="label">审核时间</span><span className="value">{selected.reviewed_at}</span></div>}
            </div>
            <p style={{ fontSize: 13, marginBottom: 12 }}>下一步：{selected.next_steps?.join("；")}</p>
            <p style={{ fontSize: 12, color: "var(--warning)", marginBottom: 12 }}>{selected.notice}</p>
            {selected.status === "pending_review" && role === "agent" && (
              <>
                <div className="form-group">
                  <label className="form-label">审核决定</label>
                  <select className="form-select" value={decision} onChange={(e) => setDecision(e.target.value as "approve" | "reject")}>
                    <option value="approve">批准</option>
                    <option value="reject">拒绝</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">审核理由</label>
                  <input className="form-input" value={reviewReason} onChange={(e) => setReviewReason(e.target.value)} />
                </div>
                <div className="actions">
                  <button className="btn btn-secondary" onClick={() => setSelected(null)}>取消</button>
                  <button className={`btn ${decision === "approve" ? "btn-primary" : "btn-danger"}`} onClick={doReview}>提交审核</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
