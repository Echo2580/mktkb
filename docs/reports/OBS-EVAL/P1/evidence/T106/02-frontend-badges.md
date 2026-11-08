# T106 证据 02：前端徽标与澄清文案

## A. 问题（ERR-05 / T103 复核）

- `MessageCard.tsx:135-139`（父提交）：clarification 零候选时，历史分支断言
  “该历史消息未保存候选明细”；`MessageView` 没有 reason 且候选未持久化，
  前端无法知道历史澄清是否曾有候选 → 文案武断。
- 无候选澄清仍显示徽标“需要确认”，暗示系统已给出可选项（ERR-04）。
- `MessageCard.tsx:64`（父提交）：历史服务错误按 `error_code !== 'MODEL_OUTPUT_INVALID'`
  推导重试，`QA_INTERNAL_ERROR` / `MODEL_NOT_CONFIGURED` 等不可重试码仍显示“重新提问”
  （T104 复核残余 3，留 T106）。

## B. 修复

1. `frontend/src/utils/format.ts:172-187`：新增 `resultBadgeLabel(kind, candidateCount)`；
   clarification 且候选为 0 → `需补充条件`（中性、可自救），有候选仍 `需要确认`。
   `RESULT_KIND_LABELS` 的 `service_error` 由“服务暂不可用”改为“服务调用失败”
   （与 ERR-07/T104 文案一致；配置/预算/内部错误不再是“暂不可用”）。
2. `MessageCard.tsx:92`：徽标改用 `resultBadgeLabel(kind, candidates.length)`；
   历史消息候选为空时显示“需补充条件”，不会显示“基于已发布资料”。
3. `MessageCard.tsx:144-153`：删除 `live ? … : 该历史消息未保存候选明细` 分叉；
   live 无候选与历史统一为“这次回答没有提供可选项，无法直接点选；请按上方提示
   补充门店、物品或更具体的条件后重新提问。”——不断言原因、不声称资料缺失。
4. `MessageCard.tsx:12-17,73-77`：历史服务错误按稳定码推导不可重试
   （`MODEL_NOT_CONFIGURED` / `MODEL_BUDGET_REFUSED` / `QA_INTERNAL_ERROR` / `INVALID_QUERY`），
   `MODEL_OUTPUT_INVALID` 仍单列；实时响应继续以服务端 `retryable` 为准。
   历史不可重试时不再渲染“重新提问”，提示改为“这类失败重试同一问题不会自行恢复…”。
5. `MessageCard.tsx:257`：服务错误卡片改为“本次问答未完成，这不是资料中没有答案。”
   （对 `INVALID_QUERY` 等服务侧/查询侧失败均成立；具体原因由响应正文与错误码给出）。

## C. e2e 同步与新增

- `frontend/e2e/02-chat.spec.ts:93`：服务错误徽标断言 `服务暂不可用` → `服务调用失败`
  （仅取值同步，未放宽）。
- `frontend/e2e/acceptance-02-kinds.spec.ts:70-103`：同上同步徽标/用例标题；
  新增 `clarification（C02）`（`:55`）：无候选澄清徽标 `需补充条件`、不出现
  `需要确认`/`该历史消息未保存`，且 `page.reload()` 后历史消息仍中性。

## D. 验证

- `npm run build`：`tsc --noEmit` + `vite build` 通过（2026-11-08，40 modules，367.01 kB JS）。
- `npx playwright test e2e/02-chat.spec.ts --project=functional`：**7 passed**。
- acceptance runner（label `t106`，端口 8188/5199）：
  `--playwright-args "e2e/acceptance-02-kinds.spec.ts"` → **PLAYWRIGHT EXIT 0**，
  JSON `expected=5 / unexpected=0`，C02 新增用例 `ok=true`。
