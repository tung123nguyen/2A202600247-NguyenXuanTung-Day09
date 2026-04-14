# Routing Decisions Log — Lab Day 09

**Nhóm:** Nhóm 07  
**Ngày:** 2026-04-14

> Ghi lại các quyết định routing thực tế từ trace của nhóm (`artifacts/traces/`).

---

## Routing Decision #1

**Task đầu vào:**
> "SLA xử lý ticket P1 là bao lâu?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `task contains SLA/ticket keyword: ['p1', 'sla']`  
**MCP tools được gọi:** Không có  
**Workers called sequence:** `["retrieval_worker", "synthesis_worker"]`

**Kết quả thực tế:**
- final_answer: "Ticket P1 có SLA phản hồi ban đầu 15 phút kể từ khi ticket được tạo. Thời gian xử lý và khắc phục là 4 giờ. Nếu không có phản hồi trong 10 phút, ticket tự động escalate lên Senior Engineer. [sla_p1_2026.txt]"
- confidence: 0.89
- Correct routing? **Yes**

**Nhận xét:** Routing đúng. Task chứa cả "P1" và "SLA" — hai keywords SLA rõ ràng, supervisor nhận diện chính xác và route sang `retrieval_worker`. Không cần policy check vì đây là câu factual lookup đơn giản.

---

## Routing Decision #2

**Task đầu vào:**
> "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi nhà sản xuất — được không?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `task contains policy/access keyword: ['hoàn tiền', 'flash sale']`  
**MCP tools được gọi:** `search_kb` (vì `needs_tool=True` và chunks chưa có khi policy worker chạy)  
**Workers called sequence:** `["policy_tool_worker", "retrieval_worker", "synthesis_worker"]`

**Kết quả thực tế:**
- final_answer: "Không. Mặc dù sản phẩm bị lỗi nhà sản xuất, đây là đơn hàng Flash Sale nên thuộc ngoại lệ không được hoàn tiền theo Điều 3 chính sách v4. Lỗi nhà sản xuất không overrides exception Flash Sale. [policy_refund_v4.txt]"
- confidence: 0.84
- Correct routing? **Yes**

**Nhận xét:** Routing đúng. Policy worker detect được `flash_sale_exception` và set `policy_applies=False`. Synthesis worker nhận được exceptions và trả lời rõ ràng "không được hoàn tiền" dù lỗi là do nhà sản xuất. Đây là test case quan trọng — nhiều người có thể nghĩ "lỗi nhà sản xuất thì được hoàn tiền", nhưng Flash Sale exception overrides điều đó.

---

## Routing Decision #3

**Task đầu vào:**
> "Contractor cần Admin Access (Level 3) để khắc phục sự cố P1 đang active. Quy trình cấp quyền tạm thời như thế nào?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `task contains policy/access keyword: ['cấp quyền', 'level 3'] | risk_high flagged: ['khẩn cấp']` (không match "khẩn cấp" chính xác trong câu, nhưng "p1 đang active" làm context rủi ro)  
**MCP tools được gọi:** `search_kb`, `get_ticket_info`  
**Workers called sequence:** `["policy_tool_worker", "retrieval_worker", "synthesis_worker"]`

**Kết quả thực tế:**
- final_answer: "Level 3 (Elevated Access) KHÔNG có emergency bypass theo Access Control SOP. Dù đang có P1, vẫn phải có approval từ đủ 3 bên: Line Manager + IT Admin + IT Security. Không thể cấp quyền tạm thời cho Level 3. [access_control_sop.txt]"
- confidence: 0.86
- Correct routing? **Yes**

**Nhận xét:** Routing đúng. Task chứa "Level 3" và "cấp quyền" → rõ ràng policy worker. MCP `check_access_permission(level=3, is_emergency=True)` trả về `emergency_override=False`, đây là thông tin quan trọng để synthesis trả lời đúng.

---

## Routing Decision #4 (bonus — câu routing khó nhất)

**Task đầu vào:**
> "ERR-403-AUTH là lỗi gì và cách xử lý như thế nào?"

**Worker được chọn:** `human_review` → sau đó `retrieval_worker`  
**Route reason:** `unknown error code detected + risk_high → escalate to human review`

**Nhận xét: Đây là trường hợp routing khó nhất. Tại sao?**

Task chứa mã lỗi không có trong bất kỳ tài liệu nào (ERR-403-AUTH). Keyword "err-" trigger `risk_high=True` và `human_review` route. Pipeline in ra warning HITL, tự động approve (lab mode), sau đó route sang `retrieval_worker` để tìm evidence. Retrieval không tìm được gì → `retrieved_chunks=[]` → synthesis abstain với "Không đủ thông tin trong tài liệu nội bộ. Liên hệ IT Helpdesk để được hỗ trợ." Đây là behavior đúng — không hallucinate mã lỗi không biết.

---

## Tổng kết

### Routing Distribution

| Worker | Số câu được route | % tổng |
|--------|------------------|--------|
| retrieval_worker | 9 | 60% |
| policy_tool_worker | 5 | 33% |
| human_review | 1 | 7% |

*(Dữ liệu từ chạy 15 test questions trong `data/test_questions.json`)*

### Routing Accuracy

- Câu route đúng: **14 / 15** (93%)
- Câu route sai: 1 câu (q02 — "hoàn tiền trong bao nhiêu ngày" bị route sang `policy_tool_worker` thay vì `retrieval_worker` vì keyword "hoàn tiền"; câu này thực chất chỉ cần retrieval đơn giản. Đã ghi nhận để cải thiện routing logic.)
- Câu trigger HITL: 1 (q09 — ERR-403-AUTH)

### Lesson Learned về Routing

1. **Keyword matching đủ dùng cho 90%+ trường hợp** trong domain CS/IT Helpdesk với 5 tài liệu. Latency ~1ms vs ~800ms nếu dùng LLM classifier. Trade-off: không handle paraphrase tốt.
2. **Policy keywords cần được ưu tiên đúng thứ tự**: khi một task có cả "P1" (SLA keyword) lẫn "cấp quyền" (policy keyword), cần quyết định rõ ràng. Nhóm quyết định policy keywords thắng vì câu đó yêu cầu compliance check, không chỉ retrieval.

### Route Reason Quality

Sau khi review tất cả trace, format `route_reason` hiện tại đủ để debug:
- Ví dụ tốt: `"task contains policy/access keyword: ['flash sale', 'hoàn tiền']"` — rõ keyword nào trigger
- Cần cải thiện: Khi policy và SLA keywords cùng xuất hiện, ghi rõ hơn tại sao chọn policy thay vì SLA

