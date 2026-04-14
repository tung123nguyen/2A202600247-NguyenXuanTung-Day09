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

Trace gq01: `route_reason: "task contains SLA/ticket keyword: ['p1', 'sla', 'ticket', 'escalation']"`, latency=15682ms.
Trace gq07: `route_reason: "task contains SLA/ticket keyword: ['p1', 'sla']"`, latency=3185ms.

---

## 3. Kết quả grading questions

**Tổng điểm raw ước tính:** 78 / 96

**Câu pipeline xử lý tốt nhất:**

- **gq01** (P1 lúc 22:47): Route sang `retrieval_worker`, trả lời đúng thông tin on-call engineer qua đường Slack và email, escalation trong 10 phút. confidence=0.59, latency=15682ms.
- **gq04** (store credit = bao nhiêu %): `policy_tool_worker` sử dụng `search_kb` lấy được thông tin 110% so với số tiền gốc. confidence=0.57, latency=2718ms.
- **gq10** (Flash Sale + lỗi nhà sản xuất + 7 ngày): Policy worker trả lời xuất sắc "Khách hàng không được hoàn tiền cho sản phẩm mua trong chương trình Flash Sale". confidence=0.66, latency=2964ms.

**Câu pipeline fail hoặc partial:**

- **gq07** (mức phạt tài chính vi phạm SLA P1): Abstain xuất sắc — do trả lời "Không đủ thông tin trong tài liệu nội bộ." với confidence thấp (0.3). Worker: `retrieval_worker`.
- **gq09** (P1 lúc 2am + Level 2 contractor): Trace ghi nhận `workers_called: ["policy_tool_worker", "synthesis_worker"]`. Trả lời khá đầy đủ các bước xử lý cũng như cần sự phê duyệt bằng lời từ Tech Lead. Tuy nhiên, latency cao (4860ms).

**Câu gq07 (abstain):** Khi tài liệu không đề cập mức phạt tài chính, pipeline đã trả về đúng "Không đủ thông tin trong tài liệu nội bộ", mô phỏng hoàn hảo behavior trong hiện thực.

**Câu gq09 (multi-hop):** Pipeline đã thành công trong việc nhận diện `policy/access keyword: ['level 2'] | risk_high flagged: ['emergency', '2am']` để gọi các tool `search_kb` và `get_ticket_info` trong `policy_tool_worker`.

---

## 4. So sánh Day 08 vs Day 09

**Metric thay đổi rõ nhất:**

- Confidence: giảm không đáng kể (-0.004) khi trung bình đạt 0.576. Từng câu đều bù trừ nhau sát sao (gq02 tăng từ 0.625 lên 0.68, gq07 giảm xuống 0.3).
- Latency: chỉ tăng trung bình 194ms (4687ms so với 4493ms) — cải thiện rất lớn về luồng xử lý nhưng overhead là cực nhỏ.

**Điều nhóm bất ngờ nhất:**

Routing module bằng Python hoạt động mạnh mẽ, hỗ trợ debug O(1) nhờ logged `route_reason`. Ưu điểm vượt trội ở Day 09 là mỗi worker có thể test độc lập, khả năng thêm tools qua MCP ("Day09 thêm tool qua MCP không sửa core; Day08 phải sửa toàn pipeline"), và tự phân luồng các risk cao.

**Trường hợp multi-agent KHÔNG giúp ích:**

Câu gq02 ("hoàn tiền") bị route sang `policy_tool_worker` vì bị khớp từ khóa trong câu hỏi. Mặc dù nó sử dụng `search_kb` để tìm được đúng thông tin, nhưng latency ở mức cao (4862ms) nếu so sánh với truy xuất thông thường của retrieval_worker trơn. Thông qua trace, có thể thấy hệ thống vẫn bị phụ thuộc khi matcher trúng từ khóa khiến worker tốn thời gian gọi tool nếu không cần thiết.

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

Phân công rõ ràng từ đầu, mỗi người có file chịu trách nhiệm chính. Contract trong `worker_contracts.yaml` được viết trước khi implement — điều này giúp Nguyễn Viết Hùng (retrieval) và Đỗ Đình Hoàn (synthesis) có thể implement song song mà không bị blocking lẫn nhau.

**Điều nhóm làm chưa tốt:**

Tích hợp policy_tool_worker với graph.py mất ~30 phút vì state field naming không khớp (`worker_io_log` vs `worker_io_logs` — số ít vs số nhiều). Nên test integration sớm hơn thay vì chờ từng worker xong mới kết nối.

**Nếu làm lại, nhóm sẽ thay đổi gì:**

Định nghĩa AgentState TypedDict và worker contracts TRƯỚC khi ai bắt đầu code. Hôm nay contract được viết song song với implementation nên vẫn có 1-2 mismatch nhỏ.

---

## 6. Nếu có thêm 1 ngày, nhóm sẽ làm gì?

Thay keyword routing bằng LLM intent classifier nhỏ. Bằng chứng từ trace: mặc dù keyword routing hoạt động tốt cho gq02, gq03 nhưng nó sẽ kém linh hoạt khi scale hoặc khi cần phân biệt rõ ngữ cảnh paraphrase nâng cao. LLM classifier sẽ linh hoạt hơn đối với paraphrase mà dự kiến latency sẽ không bị ảnh hưởng quá nghiêm trọng.

---

*File này lưu tại: `reports/group_report.md`*  
*Commit sau 18:00 được phép theo SCORING.md*
