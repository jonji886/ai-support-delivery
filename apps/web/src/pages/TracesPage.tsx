import { useState } from "react";
import { getTrace } from "../services/api";
import type { TraceData } from "../types/api";

export function TracesPage() {
  const [traceId, setTraceId] = useState("");
  const [trace, setTrace] = useState<TraceData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function search() {
    if (!traceId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getTrace(traceId.trim());
      setTrace(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setTrace(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Trace 查询</h1>
        <p className="page-subtitle">输入 Trace ID 查看完整调用链路</p>
      </div>
      <div className="filters-bar">
        <div className="form-group" style={{ flex: 1 }}>
          <input className="form-input" placeholder="Trace ID" value={traceId} onChange={(e) => setTraceId(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
        </div>
        <button className="btn btn-primary" onClick={search} disabled={loading}>查询</button>
      </div>
      {error && <div className="error-message" style={{ marginBottom: 16 }}>{error}</div>}
      {loading && <div className="loading"><div className="spinner" />加载中...</div>}
      {trace && (
        <div>
          <div className="card" style={{ marginBottom: 16 }}>
            <h3 className="card-title">Trace: {trace.trace.trace_id}</h3>
            <div className="context-item"><span className="label">Route</span><span className="value">{trace.trace.route}</span></div>
            <div className="context-item"><span className="label">Method</span><span className="value">{trace.trace.method}</span></div>
            <div className="context-item"><span className="label">Status</span><span className="value">{trace.trace.status}</span></div>
            <div className="context-item"><span className="label">Duration</span><span className="value">{trace.trace.duration_ms != null ? `${trace.trace.duration_ms}ms` : "—"}</span></div>
            {trace.trace.error_code && <div className="context-item"><span className="label">Error</span><span className="value" style={{ color: "var(--danger)" }}>{trace.trace.error_code}</span></div>}
          </div>
          <div className="card">
            <h3 className="card-title">Span 列表（{trace.spans.length}）</h3>
            <div className="trace-tree">
              {trace.spans.map((s) => (
                <div key={s.span_id} className="trace-span" style={{ marginLeft: s.parent_span_id ? 24 : 0 }}>
                  <span className="span-name">{s.name}</span>
                  <span className="span-duration">{s.duration_ms}ms</span>
                  <span className="badge badge-default" style={{ marginLeft: 8 }}>{s.kind}</span>
                  {s.status !== "ok" && <span className="span-error"> · {s.error_code || s.status}</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
