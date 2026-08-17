import { useState, useEffect } from "react";
import { getObservabilitySummary } from "../services/api";
import type { ObservabilitySummary } from "../types/api";

export function ObservabilityPage() {
  const [data, setData] = useState<ObservabilitySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [window, setWindow] = useState(60);

  useEffect(() => {
    getObservabilitySummary(window).then(setData).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [window]);

  if (error) return <div className="error-message">{error}</div>;
  if (!data) return <div className="loading"><div className="spinner" />加载中...</div>;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">可观测性</h1>
        <p className="page-subtitle">最近 {window} 分钟</p>
      </div>
      <div className="filters-bar">
        <div className="form-group">
          <select className="form-select" value={window} onChange={(e) => setWindow(Number(e.target.value))}>
            <option value={15}>15 分钟</option>
            <option value={60}>60 分钟</option>
            <option value={360}>6 小时</option>
            <option value={1440}>24 小时</option>
          </select>
        </div>
      </div>
      <div className="metrics-grid">
        <div className="metric-card"><div className="metric-value">{data.request_count}</div><div className="metric-label">请求数</div></div>
        <div className="metric-card"><div className="metric-value" style={{ color: data.request_error_rate > 0.1 ? "var(--danger)" : "inherit" }}>{(data.request_error_rate * 100).toFixed(1)}%</div><div className="metric-label">错误率</div></div>
        <div className="metric-card"><div className="metric-value">{data.request_latency_ms.p95 != null ? `${data.request_latency_ms.p95}` : "—"}</div><div className="metric-label">P95 延迟(ms)</div></div>
        <div className="metric-card"><div className="metric-value">{data.request_latency_ms.avg != null ? `${data.request_latency_ms.avg}` : "—"}</div><div className="metric-label">平均延迟(ms)</div></div>
      </div>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 className="card-title">操作指标</h3>
        <div className="table-container">
          <table>
            <thead><tr><th>Operation</th><th>Count</th><th>Errors</th><th>Error Rate</th><th>Avg(ms)</th><th>P95(ms)</th></tr></thead>
            <tbody>
              {data.operations.map((op) => (
                <tr key={op.operation}>
                  <td><code>{op.operation}</code></td>
                  <td>{op.count}</td>
                  <td>{op.error_count}</td>
                  <td style={{ color: op.error_rate > 0.1 ? "var(--danger)" : "inherit" }}>{(op.error_rate * 100).toFixed(1)}%</td>
                  <td>{op.latency_ms.avg}</td>
                  <td>{op.latency_ms.p95 ?? "—"}</td>
                </tr>
              ))}
              {data.operations.length === 0 && <tr><td colSpan={6} style={{ textAlign: "center", color: "var(--text-secondary)" }}>暂无数据</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      {data.slowest_traces.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 className="card-title">最慢 Trace</h3>
          <div className="table-container">
            <table>
              <thead><tr><th>Trace ID</th><th>Route</th><th>Duration(ms)</th><th>Status</th></tr></thead>
              <tbody>
                {data.slowest_traces.map((t) => (
                  <tr key={t.trace_id}><td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{t.trace_id}</td><td>{t.route}</td><td>{t.duration_ms}</td><td>{t.status}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {data.recent_failed_traces.length > 0 && (
        <div className="card">
          <h3 className="card-title">最近失败 Trace</h3>
          <div className="table-container">
            <table>
              <thead><tr><th>Trace ID</th><th>Route</th><th>Error Code</th><th>Error Type</th></tr></thead>
              <tbody>
                {data.recent_failed_traces.map((t) => (
                  <tr key={t.trace_id}><td style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{t.trace_id}</td><td>{t.route}</td><td><code>{t.error_code}</code></td><td>{t.error_type}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
