# Single Agent vs Multi-Agent Comparison — Lab Day 09

**Nhóm:** Nhóm 07  
**Ngày:** 2026-04-14

> So sánh Day 08 (single-agent RAG) với Day 09 (supervisor-worker).
> Số liệu Day 09 từ `artifacts/eval_report.json`; Day 08 từ ước tính baseline do không có artifact.

---

## 1. Metrics Comparison

| Metric | Day 08 (Single Agent) | Day 09 (Multi-Agent) | Delta | Ghi chú |
|--------|----------------------|---------------------|-------|---------|
| Avg confidence | ~0.72 | 0.81 | +0.09 | Day 09 grounded hơn nhờ policy layer |
| Avg latency (ms) | ~850 | ~1320 | +470ms | Multi-agent thêm ~1 LLM call cho câu phức tạp |
| Abstain rate (%) | ~13% | 7% | -6% | Multi-agent abstain ít hơn nhờ MCP fallback |
| Multi-hop accuracy | ~40% | 73% | +33% | Cải thiện rõ nhất với câu cross-doc |
| Routing visibility | Không có | Có `route_reason` | N/A | 100% trace có route_reason |
| Debug time (estimate) | ~15 phút | ~4 phút | -11 phút | Xem trace → xác định worker sai ngay |
| Hallucination rate | ~20% | 6% | -14% | Policy layer chặn được nhiều hallucination |

> **Lưu ý:** Day 08 confidence và latency là ước tính từ nhóm (không có eval.py artifact từ Day 08). Các số liệu Day 09 là thực tế từ chạy 15 test questions.

---

## 2. Phân tích theo loại câu hỏi

### 2.1 Câu hỏi đơn giản (single-document)

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Accuracy | ~85% | ~87% | 
| Latency | ~650ms | ~950ms |
| Observation | Trả lời đủ nhưng đôi khi không cite nguồn | Luôn có citation; nhưng thêm ~300ms do routing step |

**Kết luận:** Với câu đơn giản, multi-agent không cải thiện accuracy đáng kể nhưng thêm latency ~300ms. Trade-off không lý tưởng. Tuy nhiên, routing bước thêm đảm bảo trace rõ ràng hơn.

### 2.2 Câu hỏi multi-hop (cross-document)

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Accuracy | ~40% | ~73% |
| Routing visible? | Không | Có |
| Observation | Single agent không biết cần đọc cả hai doc; hay trả lời từ 1 doc duy nhất | Policy worker + retrieval worker được gọi tuần tự; synthesis nhận được full context |

**Kết luận:** Multi-agent cải thiện rõ rệt với câu multi-hop. Ví dụ câu q15 (P1 lúc 2am + Level 2 access): Day 08 thường chỉ trả lời được 1 trong 2 phần; Day 09 pipeline gọi cả `retrieval_worker` (SLA) và `policy_tool_worker` (access control), synthesis nhận đủ context.

### 2.3 Câu hỏi cần abstain

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Abstain rate | ~13% | 7% |
| Hallucination cases | ~20% | 6% |
| Observation | Single agent hay "bịa" câu trả lời có vẻ hợp lý khi thiếu context | Synthesis worker có SYSTEM_PROMPT nghiêm ngặt; `retrieved_chunks=[]` luôn trigger abstain |

**Kết luận:** Câu q07 (abstain về financial penalty SLA P1 — không có trong docs): Day 09 trả lời "Không có thông tin về mức phạt tài chính trong tài liệu nội bộ hiện tại. Vui lòng liên hệ IT Management." → đúng abstain. Day 08 hay tự bịa con số.

---

## 3. Debuggability Analysis

### Day 08 — Debug workflow
```
Khi answer sai → phải đọc toàn bộ RAG pipeline code
→ Không biết lỗi ở indexing, retrieval, hay generation
→ Không có trace → phải add print() vào từng bước
Thời gian ước tính: 15 phút để xác định root cause
```

### Day 09 — Debug workflow
```
Khi answer sai → đọc trace JSON → xem supervisor_route + route_reason
  → Nếu route sai (VD: SLA câu bị route sang policy) → sửa routing keywords
  → Nếu retrieval sai → test retrieval_worker độc lập với cùng query
  → Nếu synthesis sai → xem retrieved_chunks, kiểm tra prompt
Thời gian ước tính: 4 phút để xác định root cause
```

**Câu cụ thể nhóm đã debug:**

Câu q02 ("hoàn tiền trong bao nhiêu ngày") bị route sang `policy_tool_worker` thay vì `retrieval_worker`. Trace cho thấy ngay: `route_reason: "task contains policy/access keyword: ['hoàn tiền']"`. Root cause: keyword "hoàn tiền" quá rộng — câu này chỉ là lookup đơn giản, không cần policy check. Fix: thêm điều kiện kiểm tra nếu task chỉ có "hoàn tiền" (không có context thêm như "flash sale", "được không", "exception") thì route sang `retrieval_worker`. Sửa xong trong 3 phút nhờ trace rõ ràng.

---

## 4. Extensibility Analysis

| Scenario | Day 08 | Day 09 |
|---------|--------|--------|
| Thêm 1 tool/API mới | Phải sửa toàn prompt và test lại toàn pipeline | Thêm hàm vào `mcp_server.py` + 1 routing rule |
| Thêm 1 domain mới | Phải retrain/re-prompt agent lớn | Thêm 1 worker mới, supervisor thêm route rule |
| Thay đổi retrieval strategy | Sửa trực tiếp trong pipeline | Sửa `workers/retrieval.py` độc lập |
| A/B test một phần | Khó — phải clone toàn pipeline | Dễ — swap worker function |

**Nhận xét:**

Khi cần thêm tool `check_access_permission` vào Day 09, nhóm chỉ cần thêm hàm vào `mcp_server.py` và thêm 2 dòng trong `policy_tool.py`. Không đụng đến `graph.py`, `retrieval.py`, hay `synthesis.py`. Với Day 08, phải sửa system prompt và test lại toàn bộ.

---

## 5. Cost & Latency Trade-off

| Scenario | Day 08 calls | Day 09 calls |
|---------|-------------|-------------|
| Simple query | 1 LLM call | 1 LLM call (synthesis) |
| Policy query (no chunks) | 1 LLM call | 1 MCP call + 1 LLM call |
| Multi-hop complex query | 1 LLM call | 1 MCP call + 1 LLM call |
| MCP tool call | N/A | ~0-5ms (mock) / ~50-200ms (real HTTP) |

**Nhận xét về cost-benefit:**

Day 09 không tốn nhiều LLM calls hơn Day 08 trong thực tế — synthesis vẫn là 1 LLM call duy nhất. Chi phí thêm chủ yếu là overhead routing (~1ms keyword matching) và MCP calls (~5ms mock). Với production HTTP MCP server, overhead tăng lên ~50-200ms. Đây là trade-off chấp nhận được vì accuracy và debuggability tăng rõ rệt.

---

## 6. Kết luận

**Multi-agent tốt hơn single agent ở điểm nào?**

1. **Multi-hop accuracy**: tăng từ ~40% lên ~73% cho câu yêu cầu cross-document reasoning. Pipeline có thể gọi retrieval + policy workers tuần tự và synthesis nhận đủ context.
2. **Debuggability**: giảm debug time từ ~15 phút xuống ~4 phút. `route_reason` trong trace cho biết ngay tại sao câu đó được route sang worker nào.
3. **Anti-hallucination**: policy layer với exception detection giảm hallucination từ ~20% xuống ~6%.

**Multi-agent kém hơn hoặc không khác biệt ở điểm nào?**

1. **Latency cho câu đơn giản**: thêm ~300ms routing overhead không mang lại accuracy benefit. Single agent nhanh hơn cho câu lookup đơn giản.

**Khi nào KHÔNG nên dùng multi-agent?**

Khi tất cả câu hỏi đều là single-document lookup đơn giản, không có policy exceptions, và không có multi-hop requirements. Overhead của supervisor + routing không justify với use case đó.

**Nếu tiếp tục phát triển hệ thống này, nhóm sẽ thêm gì?**

LLM-based routing classifier (thay cho keyword matching) để handle paraphrase tốt hơn. Dùng fast model (Haiku/Flash) cho bước classify, không ảnh hưởng nhiều đến latency nhưng tăng routing accuracy từ ~93% lên ~98%.

