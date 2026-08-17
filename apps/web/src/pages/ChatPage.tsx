import { useState, useRef, useEffect } from "react";
import { assist, queryOrderLogistics, submitReturnApplication, getReturnApplication } from "../services/api";
import type { Role, ToolResponse, Citation } from "../types/api";
import type { PageId } from "../App";

interface ChatPageProps {
  role: Role;
  userId: string;
  prefill?: { message: string; orderId?: string };
  onNavigate: (p: PageId) => void;
}

interface ChatMessage {
  id: string;
  role: "user" | "ai" | "system";
  text: string;
  citations?: Citation[];
  toolResults?: { name: string; data: unknown }[];
  handoff?: boolean;
  citationRefusal?: boolean;
  traceId?: string;
}

export function ChatPage({ role, userId, prefill, onNavigate }: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState<{ orderId?: string; returnReason?: string }>({});
  const [confirmation, setConfirmation] = useState<{
    type: "submit_return";
    orderId: string;
    returnReason: string;
    idempotencyKey: string;
    eligibilityData?: unknown;
  } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const prefillUsed = useRef(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (prefill && !prefillUsed.current) {
      prefillUsed.current = true;
      if (prefill.orderId) {
        setContext((c) => ({ ...c, orderId: prefill.orderId }));
      }
      setInput(prefill.message);
    }
  }, [prefill]);

  async function send(message?: string) {
    const text = message ?? input;
    if (!text.trim() || loading) return;

    setError(null);
    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await assist(text, userId, {
        order_id: context.orderId,
        return_reason: context.returnReason,
      });

      handleAssistResponse(res);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(`请求失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }

  function handleAssistResponse(res: ToolResponse) {
    if (res.success && res.data) {
      const data = res.data as Record<string, unknown>;
      const aiMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "ai",
        text: (data.answer as string) || "",
        traceId: res.trace_id,
      };

      if (data.citations) {
        aiMsg.citations = data.citations as Citation[];
      }
      if (data.citation_refusal) {
        aiMsg.citationRefusal = true;
      }
      if (data.tool_results) {
        aiMsg.toolResults = data.tool_results as { name: string; data: unknown }[];
      }
      if (res.handoff || data.handoff) {
        aiMsg.handoff = true;
      }

      // Update context from extracted state
      if (data.extracted_state) {
        const state = data.extracted_state as Record<string, unknown>;
        setContext((c) => ({
          orderId: (state.order_id as string) || c.orderId,
          returnReason: (state.return_reason as string) || c.returnReason,
        }));
      }

      // Check for pending confirmation
      if (res.error_code === "409_SKILL_CONFIRMATION_REQUIRED" && data.pending_action) {
        const action = data.pending_action as Record<string, unknown>;
        setConfirmation({
          type: "submit_return",
          orderId: action.order_id as string,
          returnReason: action.return_reason as string,
          idempotencyKey: action.idempotency_key as string,
          eligibilityData: action.eligibility,
        });
      }

      setMessages((prev) => [...prev, aiMsg]);
    } else if (res.error_code === "409_SKILL_CONFIRMATION_REQUIRED" && res.data) {
      const data = res.data as Record<string, unknown>;
      const action = data.pending_action as Record<string, unknown>;
      setConfirmation({
        type: "submit_return",
        orderId: action.order_id as string,
        returnReason: action.return_reason as string,
        idempotencyKey: action.idempotency_key as string,
        eligibilityData: action.eligibility,
      });
      // Also show AI message if present
      if (data.answer) {
        setMessages((prev) => [
          ...prev,
          { id: crypto.randomUUID(), role: "ai", text: data.answer as string, traceId: res.trace_id },
        ]);
      }
    } else {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "ai",
        text: res.message || "请求失败",
        traceId: res.trace_id,
      };
      setMessages((prev) => [...prev, errMsg]);
    }
  }

  async function confirmSubmitReturn() {
    if (!confirmation) return;
    setLoading(true);
    setError(null);
    try {
      const res = await submitReturnApplication(
        confirmation.orderId,
        confirmation.returnReason,
        confirmation.idempotencyKey,
        userId
      );
      if (res.success && res.data) {
        const data = res.data as Record<string, unknown>;
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "ai",
            text: `退货申请已提交。申请编号：${data.application_id}\n状态：${data.status}\n下一步：${(data.next_steps as string[])?.join("；") || ""}`,
            toolResults: [{ name: "submit_return_application", data }],
            traceId: res.trace_id,
          },
        ]);
      } else {
        setError(`提交失败: ${res.message}`);
      }
      setConfirmation(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(`提交失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }

  function cancelConfirmation() {
    setConfirmation(null);
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "system", text: "已取消写操作" },
    ]);
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Agent Chat</h1>
        <p className="page-subtitle">
          User: {userId} · Role: <span className="role-badge">{role}</span>
        </p>
      </div>
      <div className="chat-container">
        <div className="chat-main">
          <div className="chat-messages">
            {messages.length === 0 && (
              <div className="empty-state">发送消息开始对话。可尝试：查询订单 OD001 物流。</div>
            )}
            {messages.map((msg) => (
              <div key={msg.id} className={`message ${msg.role}${msg.citationRefusal ? " citation-refusal" : ""}`}>
                {msg.text}
                {msg.toolResults?.map((tr, i) => (
                  <div key={i} className="tool-result">
                    [Tool: {tr.name}]
                    {JSON.stringify(tr.data, null, 2)}
                  </div>
                ))}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="citation">
                    <strong>引用来源：</strong>
                    {msg.citations.map((c, i) => (
                      <div key={i}>
                        [{i + 1}] {c.title} (v{c.version}, {c.status}) — {c.source}#{c.chunk_id}
                      </div>
                    ))}
                  </div>
                )}
                {msg.handoff && (
                  <div className="handoff-banner">
                    ⚠️ 已触发人工接管，工单已创建。客服将在工作时间内处理。
                  </div>
                )}
                {msg.traceId && (
                  <div className="citation" style={{ fontSize: 11 }}>
                    <strong>Trace:</strong>{" "}
                    <span
                      style={{ cursor: "pointer", color: "var(--primary)" }}
                      onClick={() => onNavigate("traces")}
                    >
                      {msg.traceId}
                    </span>
                  </div>
                )}
              </div>
            ))}
            {loading && (
              <div className="message ai">
                <div className="spinner" style={{ display: "inline-block", verticalAlign: "middle" }} />
                思考中...
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          {error && <div className="error-message" style={{ margin: "0 16px 8px" }}>{error}</div>}
          <div className="chat-input-area">
            <input
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="输入消息..."
              disabled={loading}
            />
            <button className="btn btn-primary" onClick={() => send()} disabled={loading}>
              发送
            </button>
          </div>
        </div>
        <div className="chat-sidebar">
          <div className="context-panel">
            <h4>当前上下文</h4>
            <div className="context-item">
              <span className="label">Order ID</span>
              <span className="value">{context.orderId || "—"}</span>
            </div>
            <div className="context-item">
              <span className="label">Return Reason</span>
              <span className="value">{context.returnReason || "—"}</span>
            </div>
          </div>
          <div className="context-panel">
            <h4>快捷 Tool 调用</h4>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <button
                className="btn btn-secondary"
                onClick={async () => {
                  const oid = context.orderId || "OD001";
                  const res = await queryOrderLogistics(oid, userId);
                  setMessages((prev) => [
                    ...prev,
                    {
                      id: crypto.randomUUID(),
                      role: "ai",
                      text: `[直接调用] query_order_logistics(${oid})`,
                      toolResults: [{ name: "query_order_logistics", data: res.data }],
                    },
                  ]);
                }}
              >
                查询物流
              </button>
              <button
                className="btn btn-secondary"
                onClick={async () => {
                  const oid = prompt("Application ID:", "APP-DEMO-001");
                  if (!oid) return;
                  const res = await getReturnApplication(oid, userId);
                  setMessages((prev) => [
                    ...prev,
                    {
                      id: crypto.randomUUID(),
                      role: "ai",
                      text: `[直接调用] get_return_application(${oid})`,
                      toolResults: [{ name: "get_return_application", data: res.data }],
                    },
                  ]);
                }}
              >
                查询退货申请
              </button>
            </div>
          </div>
          <div className="context-panel">
            <h4>能力说明</h4>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.8 }}>
              <p>• 订单物流查询（Tool）</p>
              <p>• 退货政策问答（RAG + 引用）</p>
              <p>• 退货申请（写操作需确认）</p>
              <p>• 风险场景人工接管</p>
              <p>• 多轮上下文记忆</p>
              <p>• 无证据拒答</p>
            </div>
          </div>
        </div>
      </div>

      {confirmation && (
        <div className="confirm-overlay">
          <div className="confirm-dialog">
            <h3>确认写操作</h3>
            <p>
              即将提交退货申请：
              <br />
              订单号：<strong>{confirmation.orderId}</strong>
              <br />
              退货原因：<strong>{confirmation.returnReason}</strong>
            </p>
            {confirmation.eligibilityData && (
              <div style={{ marginBottom: 16, fontSize: 13, color: "var(--text-secondary)" }}>
                资格校验结果：{JSON.stringify(confirmation.eligibilityData)}
              </div>
            )}
            <div className="actions">
              <button className="btn btn-secondary" onClick={cancelConfirmation} disabled={loading}>
                取消
              </button>
              <button className="btn btn-danger" onClick={confirmSubmitReturn} disabled={loading}>
                确认提交
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
