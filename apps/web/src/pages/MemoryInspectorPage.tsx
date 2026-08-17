import { useState, useEffect } from "react";
import { listMemory } from "../services/api";
import type { MemoryItem, MemoryListResponse } from "../types/api";

export function MemoryInspectorPage() {
  const [userId, setUserId] = useState("user-001");
  const [memoryType, setMemoryType] = useState("");
  const [data, setData] = useState<MemoryListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await listMemory(userId, memoryType || undefined);
      setData(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []); // eslint-disable-line

  function typeBadgeClass(t: string): string {
    if (t.startsWith("working")) return "memory-type-working";
    if (t.startsWith("conversation")) return "memory-type-conversation";
    if (t.startsWith("profile")) return "memory-type-profile";
    if (t.startsWith("episodic")) return "memory-type-episodic";
    return "badge-default";
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Memory Inspector</h1>
        <p className="page-subtitle">查看用户级 Memory：类型、值、来源、置信度、生命周期</p>
      </div>
      <div className="filters-bar">
        <div className="form-group">
          <label className="form-label">User ID</label>
          <input className="form-input" value={userId} onChange={(e) => setUserId(e.target.value)} />
        </div>
        <div className="form-group">
          <label className="form-label">Memory Type</label>
          <select className="form-select" value={memoryType} onChange={(e) => setMemoryType(e.target.value)}>
            <option value="">全部</option>
            <option value="working">working</option>
            <option value="conversation">conversation</option>
            <option value="conversation_summary">conversation_summary</option>
            <option value="profile">profile</option>
            <option value="episodic">episodic</option>
          </select>
        </div>
        <button className="btn btn-primary" onClick={load} disabled={loading}>查询</button>
      </div>

      {error && <div className="error-message" style={{ marginBottom: 16 }}>{error}</div>}
      {loading ? <div className="loading"><div className="spinner" />加载中...</div>
      : data && data.memories.length > 0 ? (
        <div className="card">
          <h3 className="card-title">Memory 列表（{data.total}）</h3>
          <div className="table-container">
            <table className="memory-table">
              <thead>
                <tr>
                  <th>Type</th><th>Key</th><th>Value</th><th>Source</th><th>Confidence</th>
                  <th>Scope</th><th>Order</th><th>Session</th><th>Status</th>
                  <th>Created</th><th>Updated</th><th>Expires</th>
                </tr>
              </thead>
              <tbody>
                {data.memories.map((m: MemoryItem) => (
                  <tr key={m.memory_id}>
                    <td><span className={`memory-type-badge ${typeBadgeClass(m.memory_type)}`}>{m.memory_type}</span></td>
                    <td><code>{m.key}</code></td>
                    <td className="memory-value" title={JSON.stringify(m.value)}>{JSON.stringify(m.value)}</td>
                    <td><span className="badge badge-info">{m.source}</span></td>
                    <td>{m.confidence.toFixed(2)}</td>
                    <td>{m.scope}</td>
                    <td>{m.scope_order_id || "—"}</td>
                    <td style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{m.session_id ? m.session_id.slice(0, 8) : "—"}</td>
                    <td><span className={`badge ${m.status === "active" ? "badge-success" : "badge-default"}`}>{m.status}</span></td>
                    <td style={{ fontSize: 11 }}>{m.created_at}</td>
                    <td style={{ fontSize: 11 }}>{m.updated_at}</td>
                    <td style={{ fontSize: 11 }}>{m.expires_at || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : data ? (
        <div className="empty-state">该用户暂无 Memory 记录</div>
      ) : null}

      <div className="card" style={{ marginTop: 20 }}>
        <h3 className="card-title">Memory 体系说明</h3>
        <div className="table-container">
          <table>
            <thead>
              <tr><th>Memory Type</th><th>用途</th><th>生命周期</th><th>存储</th></tr>
            </thead>
            <tbody>
              <tr><td><span className="memory-type-badge memory-type-working">working</span></td><td>当前 Agent 执行的业务状态</td><td>Request / TTL</td><td>LangGraph State / SQLite</td></tr>
              <tr><td><span className="memory-type-badge memory-type-conversation">conversation</span></td><td>最近对话窗口</td><td>Session</td><td>SQLite Memory Store</td></tr>
              <tr><td><span className="memory-type-badge memory-type-conversation">conversation_summary</span></td><td>对话摘要</td><td>Session</td><td>SQLite Memory Store</td></tr>
              <tr><td><span className="memory-type-badge memory-type-profile">profile</span></td><td>稳定用户偏好</td><td>Long-term</td><td>SQLite Memory Store</td></tr>
              <tr><td><span className="memory-type-badge memory-type-episodic">episodic</span></td><td>历史事件摘要</td><td>Long-term</td><td>SQLite Memory Store</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
