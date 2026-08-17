interface GuidePageProps {
  onDemo: (message: string, orderId?: string) => void;
}

const DEMOS = [
  {
    title: "查询订单物流",
    description: "AI 调用 query_order_logistics Tool，返回结构化物流信息。",
    hint: "我的订单 OD001 到哪了？",
    orderId: "OD001",
  },
  {
    title: "退货政策问答（RAG）",
    description: "基于政策知识库检索，回答退货窗口、条件，附带引用。",
    hint: "7天无理由退货的条件是什么？",
  },
  {
    title: "提交退货申请",
    description: "高风险写操作：先校验资格、再请求用户确认、最后幂等提交。",
    hint: "帮我申请退货，订单 OD002，商品损坏",
    orderId: "OD002",
  },
  {
    title: "人工接管",
    description: "风险场景触发人工接管，创建工单进入客服队列。",
    hint: "我要投诉快递员态度恶劣，要求处理",
  },
  {
    title: "多轮上下文记忆",
    description: "同一订单多轮对话不重复询问订单号。",
    hint: "订单 OD001 到哪了？",
    orderId: "OD001",
  },
  {
    title: "无证据拒答",
    description: "政策知识库无相关内容时，AI 明确拒答而非编造。",
    hint: "你们支持比特币支付吗？",
  },
];

export function GuidePage({ onDemo }: GuidePageProps) {
  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">使用指引</h1>
        <p className="page-subtitle">点击下方场景卡片，快速体验 Agent Chat</p>
      </div>
      <div className="guide-grid">
        {DEMOS.map((d) => (
          <div key={d.title} className="guide-card" onClick={() => onDemo(d.hint, d.orderId)}>
            <h3>{d.title}</h3>
            <p>{d.description}</p>
            <div className="demo-hint">{d.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
