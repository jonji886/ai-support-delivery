import { useState, useEffect } from "react";
import { getMetrics } from "../services/api";
import type { Metrics } from "../types/api";

export function MetricsPage() {
  const [data, setData] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMetrics().then(setData).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <div className="error-message">{error}</div>;
  if (!data) return <div className="loading"><div className="spinner" />加载中...</div>;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">基础指标</h1>
        <p className="page-subtitle">全局运行指标与趋势</p>
      </div>
      <div className="metrics-grid">
        <div className="metric-card"><div className="metric-value">{data.conversation_count}</div><div className="metric-label">会话总数</div></div>
        <div className="metric-card"><div className="metric-value">{data.tool_calls}</div><div className="metric-label">Tool 调用</div></div>
        <div className="metric-card"><div className="metric-value">{data.tool_success_rate != null ? `${(data.tool_success_rate * 100).toFixed(1)}%` : "—"}</div><div className="metric-label">Tool 成功率</div></div>
        <div className="metric-card"><div className="metric-value">{data.handoff_count}</div><div className="metric-label">人工接管</div></div>
        <div className="metric-card"><div className="metric-value">{data.handoff_rate != null ? `${(data.handoff_rate * 100).toFixed(1)}%` : "—"}</div><div className="metric-label">接管率</div></div>
        <div className="metric-card"><div className="metric-value">{data.citation_rate != null ? `${(data.citation_rate * 100).toFixed(1)}%` : "—"}</div><div className="metric-label">引用率</div></div>
        <div className="metric-card"><div className="metric-value">{data.risk_count}</div><div className="metric-label">风险事件</div></div>
      </div>
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
        <div className="card" style={{ flex: "1 1 300px" }}>
          <h3 className="card-title">意图分布</h3>
          <div className="table-container">
            <table>
              <thead><tr><th>Intent</th><th>Count</th></tr></thead>
              <tbody>
                {Object.entries(data.intent_distribution || {}).map(([k, v]) => (
                  <tr key={k}><td>{k}</td><td>{v}</td></tr>
                ))}
                {Object.keys(data.intent_distribution || {}).length === 0 && <tr><td colSpan={2} style={{ textAlign: "center", color: "var(--text-secondary)" }}>暂无数据</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card" style={{ flex: "1 1 300px" }}>
          <h3 className="card-title">错误分布</h3>
          <div className="table-container">
            <table>
              <thead><tr><th>Error Code</th><th>Count</th></tr></thead>
              <tbody>
                {Object.entries(data.error_distribution || {}).map(([k, v]) => (
                  <tr key={k}><td><code>{k}</code></td><td>{v}</td></tr>
                ))}
                {Object.keys(data.error_distribution || {}).length === 0 && <tr><td colSpan={2} style={{ textAlign: "center", color: "var(--text-secondary)" }}>暂无错误</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      {data.trend && data.trend.length > 0 && (
        <div className="card" style={{ marginTop: 20 }}>
          <h3 className="card-title">趋势</h3>
          <div className="table-container">
            <table>
              <thead><tr><th>时间</th><th>会话</th><th>接管</th><th>Tool 成功率</th></tr></thead>
              <tbody>
                {data.trend.map((t, i) => (
                  <tr key={i}>
                    <td>{t.label}</td><td>{t.conversations}</td><td>{t.handoffs}</td>
                    <td>{t.tool_success_rate != null ? `${(t.tool_success_rate * 100).toFixed(1)}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
