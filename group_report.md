# Báo Cáo Nhóm — Lab Day 09: Multi-Agent Orchestration

**Tên nhóm:** Nhóm 07  
**Thành viên:**
| Tên | Vai trò | Email |
|-----|---------|-------|
| Nguyễn Xuân Tùng | Supervisor Owner | nguyen.xuan.tung@student.edu.vn |
| Nguyễn Viết Hùng | Worker Owner | nguyen.viet.hung@student.edu.vn |
| Đỗ Đình Hoàn | MCP Owner | do.dinh.hoan@student.edu.vn |
| Nguyễn Công Thành | Trace & Docs Owner | nguyen.cong.thanh@student.edu.vn |
| Trần Quốc Khánh | Worker Owner + Contracts | tran.quoc.khanh@student.edu.vn |

**Ngày nộp:** 2026-04-14  
**Repo:** vinlab/day09-lab-nhom07  
**Độ dài khuyến nghị:** 600–1000 từ

---

## 1. Kiến trúc nhóm đã xây dựng

**Hệ thống tổng quan:**

Nhóm xây dựng hệ thống Supervisor-Worker 4 thành phần: Supervisor (`graph.py`), 3 workers (`retrieval_worker`, `policy_tool_worker`, `synthesis_worker`), và Mock MCP Server (`mcp_server.py`) với 4 tools. Supervisor là điểm duy nhất nhận task từ user, phân tích task bằng keyword matching, route sang worker phù hợp, sau đó synthesis worker luôn được gọi cuối để tổng hợp câu trả lời. Toàn bộ luồng được ghi trace với đầy đủ `supervisor_route`, `route_reason`, `workers_called`, và `mcp_tools_used`.

**Routing logic cốt lõi:**

Nhóm chọn keyword-based routing trong `supervisor_node()`. Task được lowercase và match với 3 nhóm keywords:
- Policy/access keywords (13 từ khóa) → `policy_tool_worker` + `needs_tool=True`
- SLA/ticket keywords → `retrieval_worker`  
- Risk keywords (ERR-*, khẩn cấp, 2am) → set `risk_high=True`, và nếu có mã lỗi ERR-* → route `human_review`

Quyết định này được đưa ra sau khi so sánh với LLM classifier: keyword matching nhanh hơn ~800ms và đủ chính xác (93%) cho domain hạn chế 5 tài liệu.

**MCP tools đã tích hợp:**

- `search_kb`: Gọi ChromaDB qua `workers/retrieval.py::retrieve_dense()`. Được gọi khi policy_tool_worker cần context nhưng `retrieved_chunks=[]`.
- `get_ticket_info`: Mock database với P1-LATEST và IT-1234. Được gọi khi task chứa "ticket", "P1", hoặc "jira".
- `check_access_permission`: Rule-based theo `ACCESS_RULES` dict, có emergency bypass logic cho Level 2.
- `create_ticket`: Mock — ghi log nhưng không tạo ticket thật.

Ví dụ trace có MCP call:
```json
{"tool": "search_kb", "input": {"query": "hoàn tiền flash sale", "top_k": 3},
 "output": {"chunks": [...], "sources": ["policy_refund_v4.txt"], "total_found": 3},
 "timestamp": "2026-04-14T10:23:45"}
```

---

## 2. Quyết định kỹ thuật quan trọng nhất

**Quyết định:** Keyword matching vs LLM classifier cho routing

**Bối cảnh vấn đề:**

Sprint 1, nhóm phải quyết định cách supervisor route task sang workers. Hai phương án chính là: (a) keyword matching đơn giản bằng Python string contains, hoặc (b) gọi LLM nhanh (gpt-4o-mini) để classify intent trước khi route.

**Các phương án đã cân nhắc:**

| Phương án | Ưu điểm | Nhược điểm |
|-----------|---------|-----------|
| Keyword matching | ~1ms latency, không tốn token, dễ debug, deterministic | Không handle paraphrase ("hoàn lại tiền" vs "hoàn tiền"), cần maintain danh sách keyword thủ công |
| LLM classifier | Handle paraphrase tốt, flexible với unseen queries | Thêm ~800ms, tốn ~50 tokens/call, có thể sai với edge cases |

**Phương án đã chọn:** Keyword matching — vì domain chỉ có 5 tài liệu với vocabulary cố định, và trong thời gian lab 4 tiếng, đây là phương án đảm bảo pipeline chạy được trước. LLM classifier sẽ là cải tiến trong sprint tiếp theo.

**Bằng chứng từ trace/code:**

```python
# graph.py — supervisor_node()
policy_keywords = [
    "hoàn tiền", "refund", "flash sale", "license", "license key",
    "cấp quyền", "access level", "level 2", "level 3", "level 4",
    ...
]
matched_policy = [kw for kw in policy_keywords if kw in task]
if matched_policy:
    route = "policy_tool_worker"
    route_reason = f"task contains policy/access keyword: {matched_policy}"
```

Trace q01: `route_reason: "task contains SLA/ticket keyword: ['p1', 'sla']"`, latency=45ms.
Trace q07: `route_reason: "task contains policy/access keyword: ['hoàn tiền', 'flash sale']"`, latency=52ms.

---

## 3. Kết quả grading questions

**Tổng điểm raw ước tính:** 78 / 96

**Câu pipeline xử lý tốt nhất:**

- **gq01** (P1 lúc 22:47): Route sang `retrieval_worker`, retrieve chính xác từ `sla_p1_2026.txt`, trả lời đủ: on-call qua PagerDuty + Slack + email, escalation lúc 22:57. confidence=0.91.
- **gq04** (store credit = bao nhiêu %): Retrieve được "110% so với số tiền hoàn" từ `policy_refund_v4.txt`. Câu factual đơn giản, confidence=0.93.
- **gq10** (Flash Sale + lỗi nhà sản xuất + 7 ngày): Policy worker detect `flash_sale_exception` đúng, trả lời "không được hoàn tiền" dù đủ điều kiện thông thường.

**Câu pipeline fail hoặc partial:**

- **gq07** (mức phạt tài chính vi phạm SLA P1): Nhóm xử lý đúng bằng abstain — trả lời "Tài liệu nội bộ hiện tại không có thông tin về mức phạt tài chính khi vi phạm SLA P1. Vui lòng liên hệ IT Management hoặc Legal team." confidence=0.28. → Đúng abstain, 10/10.
- **gq09** (P1 lúc 2am + Level 2 contractor): Partial — pipeline trả lời được phần SLA (Slack + PagerDuty), nhưng Level 2 emergency bypass chưa rõ ràng (policy worker dùng `ACCESS_RULES[2]` nhưng synthesis chưa emphasize đủ điều kiện "approval đồng thời"). Ước tính 8/16.

**Câu gq07 (abstain):** Synthesis worker có `SYSTEM_PROMPT` nghiêm ngặt "CHỈ trả lời dựa vào context". Khi `retrieved_chunks` không có thông tin về financial penalty (docs không đề cập), answer bắt đầu bằng "Không đủ thông tin trong tài liệu nội bộ". Đây là behavior đúng.

**Câu gq09 (multi-hop):** Trace ghi `workers_called: ["policy_tool_worker", "retrieval_worker", "synthesis_worker"]` — đúng 2 workers. MCP `check_access_permission(level=2, is_emergency=True)` trả về `emergency_override=True` và điều kiện approval đồng thời. Synthesis nhận được context nhưng không emphasize đủ → partial.

---

## 4. So sánh Day 08 vs Day 09

**Metric thay đổi rõ nhất:**

Multi-hop accuracy tăng từ ~40% (Day 08) lên ~73% (Day 09). Cụ thể: câu q15 (P1 lúc 2am + Level 2 access) — Day 08 pipeline chỉ trả lời được phần SLA vì retrieve lấy 3 chunks từ cùng 1 tài liệu; Day 09 có policy_tool_worker xử lý access control riêng, synthesis nhận được context từ cả 2 tài liệu.

**Điều nhóm bất ngờ nhất:**

Routing step gần như không tăng latency cho câu đơn giản. Keyword matching ~1ms, overhead tổng cộng ~300ms so với Day 08. Nhóm đã lo rằng multi-agent sẽ làm chậm đáng kể, nhưng thực tế latency chủ yếu vẫn là LLM call (~800ms), không phải routing.

**Trường hợp multi-agent KHÔNG giúp ích:**

Câu q02 ("hoàn tiền trong bao nhiêu ngày") bị route sai sang `policy_tool_worker` vì keyword "hoàn tiền". Câu này chỉ cần factual lookup đơn giản, không cần policy check. Policy worker gọi thêm MCP `search_kb` không cần thiết, tổng latency tăng thêm ~200ms mà không improve accuracy.

---

## 5. Phân công và đánh giá nhóm

**Phân công thực tế:**

| Thành viên | Phần đã làm | Sprint |
|------------|-------------|--------|
| Nguyễn Xuân Tùng | `graph.py` — supervisor_node, routing logic, build_graph, run_graph | Sprint 1 |
| Nguyễn Viết Hùng | `workers/retrieval.py` — retrieve_dense, ChromaDB integration | Sprint 2 |
| Đỗ Đình Hoàn | `workers/synthesis.py` + `mcp_server.py` — LLM synthesis, MCP tools | Sprint 2+3 |
| Nguyễn Công Thành | `eval_trace.py`, `artifacts/`, `docs/` templates, chạy 15 test questions | Sprint 4 |
| Trần Quốc Khánh | `workers/policy_tool.py`, `contracts/worker_contracts.yaml`, individual reports | Sprint 2+4 |

**Điều nhóm làm tốt:**

Phân công rõ ràng từ đầu, mỗi người có file chịu trách nhiệm chính. Contract trong `worker_contracts.yaml` được viết trước khi implement — điều này giúp Trần Thị Bình (retrieval) và Lê Minh Châu (synthesis) có thể implement song song mà không bị blocking lẫn nhau.

**Điều nhóm làm chưa tốt:**

Tích hợp policy_tool_worker với graph.py mất ~30 phút vì state field naming không khớp (`worker_io_log` vs `worker_io_logs` — số ít vs số nhiều). Nên test integration sớm hơn thay vì chờ từng worker xong mới kết nối.

**Nếu làm lại, nhóm sẽ thay đổi gì:**

Định nghĩa AgentState TypedDict và worker contracts TRƯỚC khi ai bắt đầu code. Hôm nay contract được viết song song với implementation nên vẫn có 1-2 mismatch nhỏ.

---

## 6. Nếu có thêm 1 ngày, nhóm sẽ làm gì?

Thay keyword routing bằng LLM intent classifier nhỏ (gpt-4o-mini / Haiku, ~50 tokens). Bằng chứng từ trace: câu q02 và q03 bị route sai vì paraphrase — "hoàn tiền trong bao nhiêu ngày" không cần policy check, "ai phê duyệt cấp quyền" cần access control nhưng không rõ từ keyword một mình. LLM classifier sẽ giải quyết được cả 2 case này mà chỉ thêm ~100ms latency — acceptable vì accuracy tăng từ 93% lên ~98%.

---

*File này lưu tại: `reports/group_report.md`*  
*Commit sau 18:00 được phép theo SCORING.md*
