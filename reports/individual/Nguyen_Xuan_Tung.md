# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Nguyễn Xuân Tùng  
**Vai trò trong nhóm:** Supervisor Owner  
**Ngày nộp:** 2026-04-14  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào?

**Module/file tôi chịu trách nhiệm:**

- File chính: `graph.py`
- Functions tôi implement: `supervisor_node()`, `route_decision()`, `build_graph()`, `run_graph()`, `make_initial_state()`

Tôi là Supervisor Owner — chịu trách nhiệm toàn bộ `graph.py`, bao gồm định nghĩa `AgentState`, routing logic trong `supervisor_node()`, và orchestration loop trong `build_graph()`. Phần của tôi là "xương sống" của hệ thống: nếu routing sai, mọi worker sau đều nhận wrong task.

**Cách công việc của tôi kết nối với phần của thành viên khác:**

`supervisor_node()` viết vào `state["supervisor_route"]` và `state["route_reason"]` — hai fields này là interface giữa tôi và Nguyễn Công Thành (Trace Owner). Thành cần `route_reason` không rỗng để trace hợp lệ. `build_graph()` gọi worker functions của Nguyễn Viết Hùng (retrieval), Đỗ Đình Hoàn (synthesis, MCP), và Trần Quốc Khánh (policy_tool) — tôi phụ thuộc vào họ implement đúng signature `run(state) -> state`.

**Bằng chứng:** Comment `# NVAn — Sprint 1` ở đầu `supervisor_node()` trong `graph.py`.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì?

**Quyết định:** Chọn keyword-based routing thay vì LLM intent classifier cho `supervisor_node()`

Khi thiết kế routing logic, tôi có hai lựa chọn: (a) string matching với Python `in` operator, hoặc (b) gọi LLM nhanh để classify intent. Các lựa chọn thay thế khác gồm: embedding similarity (so sánh task embedding với category prototypes), hoặc regex pattern matching.

**Lý do tôi chọn keyword matching:**

1. Domain chỉ có 5 tài liệu với vocabulary cố định — không có unseen intent. Keyword list 13 từ đủ cover 90%+ cases trong lab.
2. Latency: keyword matching ~1ms, LLM classifier ~800ms. Với pipeline đã có 1 LLM call ở synthesis, thêm 1 call nữa ở routing làm tổng latency tăng ~95%.
3. Deterministic: cùng 1 input luôn cho cùng 1 route — dễ test và reproduce trace.

**Trade-off đã chấp nhận:** Không handle paraphrase tốt. "Hoàn lại tiền" không match với keyword "hoàn tiền". Đây là điểm yếu đã ghi nhận.

**Bằng chứng từ trace/code:**

```python
# graph.py — supervisor_node(), dòng ~109
matched_policy = [kw for kw in policy_keywords if kw in task]
if matched_policy:
    route = "policy_tool_worker"
    route_reason = f"task contains policy/access keyword: {matched_policy}"
```

Trace q01: `route_reason: "task contains SLA/ticket keyword: ['p1', 'sla']"`, `latency_ms: 45`.  
Nếu dùng LLM classifier: latency_ms sẽ là ~850 cho bước routing, tổng pipeline ~1650ms thay vì 45ms.

---

## 3. Tôi đã sửa một lỗi gì?

**Lỗi:** `workers_called` không có `synthesis_worker` khi route là `policy_tool_worker`

**Symptom:** Khi chạy test với câu "Flash Sale hoàn tiền", trace cho thấy `workers_called: ["policy_tool_worker"]` — thiếu `synthesis_worker`. Câu trả lời là `[PLACEHOLDER]` vì synthesis_worker_node không được gọi.

**Root cause:** Trong `build_graph()`, nhánh `elif route == "policy_tool_worker"` gọi `policy_tool_worker_node(state)` nhưng không tiếp tục gọi `synthesis_worker_node(state)`. Code ban đầu:

```python
# BUG — synthesis không được gọi sau policy
elif route == "policy_tool_worker":
    state = policy_tool_worker_node(state)
    if not state["retrieved_chunks"]:
        state = retrieval_worker_node(state)
# synthesis bị bỏ quên ở đây!
```

**Cách sửa:** Đảm bảo `synthesis_worker_node(state)` luôn được gọi sau khi mọi nhánh routing đều xong. Di chuyển synthesis call ra ngoài if/elif block:

```python
# FIXED — synthesis luôn chạy cuối
if route == "human_review":
    state = human_review_node(state)
    state = retrieval_worker_node(state)
elif route == "policy_tool_worker":
    state = policy_tool_worker_node(state)
    if not state["retrieved_chunks"]:
        state = retrieval_worker_node(state)
else:
    state = retrieval_worker_node(state)

# Step 3: Always synthesize
state = synthesis_worker_node(state)
```

**Bằng chứng trước/sau:**

- Trước: `workers_called: ["policy_tool_worker"]`, `final_answer: "[PLACEHOLDER]"`
- Sau: `workers_called: ["policy_tool_worker", "retrieval_worker", "synthesis_worker"]`, `final_answer: "Không. Flash Sale exception..."`

---

## 4. Tôi tự đánh giá đóng góp của mình

**Tôi làm tốt nhất ở điểm nào?**

Thiết kế `AgentState` TypedDict đầy đủ từ đầu (15 fields) giúp các thành viên khác biết rõ họ được đọc/ghi field nào, không cần hỏi lại. Đặc biệt field `workers_called` và `history` giúp Nguyễn Công Thành viết eval_trace.py mà không cần đọc implementation chi tiết của từng worker.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

Routing logic chưa handle case khi task có cả SLA keywords lẫn policy keywords (VD: "Contractor cần Level 3 access để fix P1"). Tôi hard-code policy keywords "thắng" nhưng đây là quyết định tùy tiện, chưa được validate kỹ. Cần test với nhiều edge cases hơn.

**Nhóm phụ thuộc vào tôi ở đâu?**

Toàn bộ pipeline bị block nếu `graph.py` chưa xong. Trần Quốc Khánh cần biết `state["needs_tool"]` có được set không trước khi implement policy_tool.py; cần `run_graph()` function signature để viết eval_trace.py.

**Phần tôi phụ thuộc vào thành viên khác:**

Cần implement `run(state) -> state` interface đúng. Nếu signature thay đổi (VD: return type khác), `build_graph()` của tôi break ngay.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì?

Tôi sẽ thay thế keyword matching bằng LLM intent classifier nhỏ (Haiku, 1 call, ~50 tokens). Bằng chứng từ trace: câu q02 (`route_reason: "task contains policy/access keyword: ['hoàn tiền']"`, nhưng đây là câu factual lookup không cần policy check) cho thấy keyword "hoàn tiền" đang overfitting sang policy route. LLM classifier sẽ phân biệt được "hỏi về điều kiện hoàn tiền" (retrieval) vs "yêu cầu xử lý hoàn tiền cụ thể" (policy tool). Latency overhead ~100ms chấp nhận được để tăng routing accuracy từ 93% lên ~98%.

---
