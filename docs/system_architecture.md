# System Architecture — Lab Day 09

**Nhóm:** Nhóm 07  
**Ngày:** 2026-04-14  
**Version:** 1.0

---

## 1. Tổng quan kiến trúc

**Pattern đã chọn:** Supervisor-Worker  
**Lý do chọn pattern này (thay vì single agent):**

Hệ thống RAG Day 08 là một monolith — một agent duy nhất vừa retrieve, vừa kiểm tra policy, vừa tổng hợp câu trả lời. Khi pipeline trả lời sai, không thể biết lỗi nằm ở bước nào. Pattern Supervisor-Worker tách biệt từng concern thành worker độc lập, mỗi worker có input/output contract rõ ràng, test và debug được độc lập.

---

## 2. Sơ đồ Pipeline

```
User Request
     │
     ▼
┌──────────────────────────────────────┐
│             Supervisor               │
│  (graph.py :: supervisor_node)       │
│  - Đọc task, phân tích keywords      │
│  - Quyết định: route, risk_high,     │
│    needs_tool, route_reason          │
└──────────────┬───────────────────────┘
               │
         [route_decision]
               │
   ┌───────────┼──────────────┐
   ▼           ▼              ▼
Retrieval   Policy Tool    Human Review
 Worker      Worker          Node
(default)  (policy/access) (HITL - err-*)
   │           │              │
   │    ┌──────┤              │
   │    │ MCP Server          │
   │    │ search_kb           │
   │    │ get_ticket_info     │
   │    │ check_access_perm   │
   │    └──────┤              │
   └─────┬─────┘              │
         │   ◄────────────────┘
         ▼
   Synthesis Worker
   (gpt-4o-mini, grounded)
   answer + citation + confidence
         │
         ▼
      Output
  (final_answer, sources,
   confidence, trace)
```

---

## 3. Vai trò từng thành phần

### Supervisor (`graph.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích task bằng keyword matching, quyết định worker nào xử lý, flag risk và tool needs |
| **Input** | `task` (câu hỏi từ user) |
| **Output** | `supervisor_route`, `route_reason`, `risk_high`, `needs_tool` |
| **Routing logic** | Policy/access keywords → `policy_tool_worker`; SLA/ticket keywords → `retrieval_worker`; ERR-* code + risk → `human_review`; default → `retrieval_worker` |
| **HITL condition** | `risk_high=True AND "err-" in task` → `human_review` node |

### Retrieval Worker (`workers/retrieval.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Semantic search trong ChromaDB, trả về top-k chunks có evidence |
| **Embedding model** | `all-MiniLM-L6-v2` (sentence-transformers) hoặc OpenAI `text-embedding-3-small` |
| **Top-k** | 3 (mặc định), có thể override qua `state["retrieval_top_k"]` |
| **Stateless?** | Yes — chỉ đọc `task`, ghi `retrieved_chunks` và `retrieved_sources` |

### Policy Tool Worker (`workers/policy_tool.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Kiểm tra policy exceptions dựa vào task + context chunks; gọi MCP tools khi cần |
| **MCP tools gọi** | `search_kb` (nếu chưa có chunks), `get_ticket_info` (nếu task liên quan ticket/P1) |
| **Exception cases xử lý** | `flash_sale_exception`, `digital_product_exception`, `activated_exception`, temporal scoping (v3 vs v4) |

### Synthesis Worker (`workers/synthesis.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **LLM model** | `gpt-4o-mini` (fallback: Gemini 1.5 Flash) |
| **Temperature** | 0.1 (low — grounded answers) |
| **Grounding strategy** | System prompt yêu cầu "chỉ dùng context được cung cấp"; citation `[source_name]` bắt buộc |
| **Abstain condition** | Nếu `retrieved_chunks=[]` → trả về "Không đủ thông tin trong tài liệu nội bộ" |

### MCP Server (`mcp_server.py`)

| Tool | Input | Output |
|------|-------|--------|
| `search_kb` | `query`, `top_k` | `chunks`, `sources`, `total_found` |
| `get_ticket_info` | `ticket_id` | ticket details + notifications |
| `check_access_permission` | `access_level`, `requester_role`, `is_emergency` | `can_grant`, `required_approvers`, `emergency_override` |
| `create_ticket` | `priority`, `title`, `description` | `ticket_id`, `url`, `created_at` |

---

## 4. Shared State Schema

| Field | Type | Mô tả | Ai đọc/ghi |
|-------|------|-------|-----------|
| `task` | str | Câu hỏi đầu vào | Supervisor đọc |
| `supervisor_route` | str | Worker được chọn | Supervisor ghi |
| `route_reason` | str | Lý do route cụ thể | Supervisor ghi |
| `risk_high` | bool | Flag risk cao | Supervisor ghi |
| `needs_tool` | bool | Có cần MCP không | Supervisor ghi |
| `retrieved_chunks` | list | Evidence từ ChromaDB | Retrieval ghi, Policy+Synthesis đọc |
| `retrieved_sources` | list | Tên files nguồn | Retrieval ghi, Synthesis đọc |
| `policy_result` | dict | Kết quả kiểm tra policy + exceptions | Policy ghi, Synthesis đọc |
| `mcp_tools_used` | list | Log các MCP tool calls | Policy ghi |
| `final_answer` | str | Câu trả lời cuối với citation | Synthesis ghi |
| `confidence` | float | Mức tin cậy 0.0–1.0 | Synthesis ghi |
| `hitl_triggered` | bool | Có trigger human review không | Human review ghi |
| `workers_called` | list | Sequence của workers đã chạy | Mỗi worker append |
| `history` | list | Log từng bước | Mọi node append |
| `latency_ms` | int | Tổng thời gian xử lý (ms) | Graph ghi sau khi hoàn thành |

---

## 5. Lý do chọn Supervisor-Worker so với Single Agent (Day 08)

| Tiêu chí | Single Agent (Day 08) | Supervisor-Worker (Day 09) |
|----------|----------------------|--------------------------|
| Debug khi sai | Khó — không rõ lỗi ở retrieval, policy, hay generation | Dễ hơn — xem `supervisor_route` + `route_reason` trong trace, test worker độc lập |
| Thêm capability mới | Phải sửa toàn prompt hoặc toàn pipeline | Thêm MCP tool mới trong `mcp_server.py`, không sửa core |
| Routing visibility | Không có — black box | Có `route_reason` trong mỗi trace entry |
| Tách biệt concerns | Không — một agent làm tất | Có — retrieval không biết về policy, synthesis không biết về routing |
| Test riêng lẻ | Chỉ test end-to-end | Mỗi worker test độc lập được |

**Quan sát thực tế từ lab:**

Trong quá trình implement, nhóm phát hiện bug trong policy_tool_worker (Flash Sale exception không detect đúng khi task dùng viết hoa "FLASH SALE"). Với multi-agent, nhóm test worker độc lập trong 2 phút và fix ngay. Nếu là single agent, phải chạy lại toàn pipeline mỗi lần test.

---

## 6. Giới hạn và điểm cần cải tiến

1. **Routing dùng keyword matching** — đơn giản nhưng không handle được paraphrase. VD: "hoàn lại tiền" không match với keyword "hoàn tiền". Cần LLM classifier để robust hơn.
2. **Policy worker không có LLM call** — dùng rule-based nên không handle được edge cases phức tạp ngoài danh sách exceptions cứng. Sprint tiếp theo: thêm LLM analysis cho unstructured exceptions.
3. **MCP server là mock class** — không phải HTTP server thật. Trong production, cần MCP HTTP server với authentication để nhiều agent cùng gọi được.
