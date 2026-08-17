import type { PageId } from "../App";
import type { Role } from "../types/api";

interface SidebarProps {
  page: PageId;
  role: Role;
  userId: string;
  onNavigate: (p: PageId) => void;
  onRoleChange: (r: Role) => void;
  onUserIdChange: (id: string) => void;
}

const NAV_SECTIONS: { section: string; items: { id: PageId; label: string; roles?: Role[] }[] }[] = [
  {
    section: "消费者",
    items: [
      { id: "guide", label: "使用指引" },
      { id: "chat", label: "Agent Chat" },
    ],
  },
  {
    section: "客服",
    items: [
      { id: "tickets", label: "工单队列" },
      { id: "returns", label: "退货审核" },
    ],
  },
  {
    section: "Supervisor",
    items: [
      { id: "metrics", label: "基础指标" },
      { id: "traces", label: "Trace 查询" },
      { id: "observability", label: "可观测性" },
      { id: "memory", label: "Memory Inspector" },
      { id: "rules", label: "规则体系" },
    ],
  },
];

export function Sidebar({ page, role, userId, onNavigate, onRoleChange, onUserIdChange }: SidebarProps) {
  return (
    <div className="sidebar">
      <div className="sidebar-logo">售后 AI 客服</div>
      {NAV_SECTIONS.map((sec) => (
        <div key={sec.section}>
          <div className="sidebar-section">{sec.section}</div>
          {sec.items.map((item) => (
            <div
              key={item.id}
              className={`sidebar-item ${page === item.id ? "active" : ""}`}
              onClick={() => onNavigate(item.id)}
            >
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      ))}
      <div className="sidebar-bottom">
        <div className="form-group">
          <label className="form-label">角色</label>
          <select
            className="form-select"
            value={role}
            onChange={(e) => onRoleChange(e.target.value as Role)}
          >
            <option value="consumer">Consumer</option>
            <option value="agent">Agent Operator</option>
            <option value="supervisor">Supervisor</option>
          </select>
        </div>
        <div className="form-group">
          <label className="form-label">User ID</label>
          <input
            className="form-input"
            value={userId}
            onChange={(e) => onUserIdChange(e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
