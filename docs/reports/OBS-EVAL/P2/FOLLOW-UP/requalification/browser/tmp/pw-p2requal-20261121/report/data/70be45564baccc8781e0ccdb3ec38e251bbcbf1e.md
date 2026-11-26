# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: acceptance-07-update.spec.ts >> acceptance-07-update · A-17 旧会话追问新值 / A-21 knowledge_changed >> A-21 回答生成期间资料更新 → knowledge_changed（中止回答且不带来源）
- Location: e2e\acceptance-07-update.spec.ts:175:3

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: locator('article.message-assistant[aria-label="知识库回答"]').last()
Expected substring: "资料已更新，本次回答已中止，请重新查询。"
Received string:    "知识库回答资料已更新07:15资料已更新，本次回答已中止，未保存旧版本答案；这不是服务故障，请基于最新资料重新查询。回答生成期间资料版本发生变化，本次回答已中止，未保存旧事实。请基于最新有效资料重新查询。重新查询"
Timeout: 10000ms

Call log:
  - Expect "toContainText" locator('article.message-assistant[aria-label="知识库回答"]').last() with timeout 10000ms
  - waiting for locator('article.message-assistant[aria-label="知识库回答"]').last()
    24 × locator resolved to <article aria-label="知识库回答" class="message-assistant">…</article>
       - unexpected value "知识库回答资料已更新07:15资料已更新，本次回答已中止，未保存旧版本答案；这不是服务故障，请基于最新资料重新查询。回答生成期间资料版本发生变化，本次回答已中止，未保存旧事实。请基于最新有效资料重新查询。重新查询"

```

```yaml
- article "知识库回答":
  - text: 知识库回答 资料已更新 07:15
  - paragraph: 资料已更新，本次回答已中止，未保存旧版本答案；这不是服务故障，请基于最新资料重新查询。
  - text: 回答生成期间资料版本发生变化，本次回答已中止，未保存旧事实。请基于最新有效资料重新查询。
  - button "重新查询"
```

# Test source

```ts
  117 |     expect(followText, '旧会话追问不得再出现旧值').not.toContain(OLD_POSITION);
  118 |     await expect(followCard.getByText('来源与依据')).toBeVisible();
  119 |     expect(followText, '来源必须指向《物品位置表》').toContain('物品位置表');
  120 |     const versionTexts = (await followCard.locator('.source-bar-version').allInnerTexts()).map((text) => text.trim());
  121 |     expect(versionTexts, `来源版本必须是最新发布的 ${updateVersionLabel}`).toContain(updateVersionLabel);
  122 |     await expect(followCard.locator('.source-bar .badge').first()).toHaveText('有效');
  123 |     await shot(page, 'a-17-03-old-session-followup-new-value');
  124 | 
  125 |     // 4) U02 另一断言：新会话同样使用新值
  126 |     await page.goto('/chat');
  127 |     await expect(page.locator('#welcome-title')).toBeVisible();
  128 |     const newCard = await askAndRead(page, POSITION_QUESTION);
  129 |     const newBadge = await cardBadge(newCard);
  130 |     const newText = await newCard.innerText();
  131 |     expect(newBadge).toBe('基于已发布资料');
  132 |     expect(newText).toContain(NEW_POSITION);
  133 |     expect(newText).not.toContain(OLD_POSITION);
  134 |     await shot(page, 'a-17-04-new-session-new-value');
  135 | 
  136 |     writeJson('acceptance-07-update/a17-update-and-followup', {
  137 |       case: ['A-17', 'U02'],
  138 |       prepare: {
  139 |         applied: prepared.applied,
  140 |         revision: prepared.revision ?? null,
  141 |         response: prepared,
  142 |       },
  143 |       update: {
  144 |         applied: update.applied,
  145 |         slot: update.slot,
  146 |         document_id: update.document_id,
  147 |         version_id: update.version_id,
  148 |         version_number: update.version_number,
  149 |         previous_active_version_id: update.previous_active_version_id ?? null,
  150 |         new_value: update.new_value,
  151 |         revision: update.revision,
  152 |       },
  153 |       old_conversation: {
  154 |         url: conversationUrl,
  155 |         first_question: POSITION_QUESTION,
  156 |         first_answer: preText,
  157 |         first_answer_contains_old_value: preText.includes(OLD_POSITION),
  158 |         followup_question: FOLLOWUP_QUESTION,
  159 |         followup_phrase_resolved_as_answer: followupPhraseResolved,
  160 |         followup_badge: followBadge,
  161 |         followup_contains_new_value: followText.includes(NEW_POSITION),
  162 |         followup_contains_old_value: followText.includes(OLD_POSITION),
  163 |         source_versions: versionTexts,
  164 |         expected_source_version: updateVersionLabel,
  165 |       },
  166 |       new_conversation: {
  167 |         question: POSITION_QUESTION,
  168 |         badge: newBadge,
  169 |         contains_new_value: newText.includes(NEW_POSITION),
  170 |         contains_old_value: newText.includes(OLD_POSITION),
  171 |       },
  172 |     });
  173 |   });
  174 | 
  175 |   test('A-21 回答生成期间资料更新 → knowledge_changed（中止回答且不带来源）', async ({ page, request }) => {
  176 |     test.setTimeout(300_000);
  177 | 
  178 |     await page.goto('/login');
  179 |     await loginViaUi(page, 'admin');
  180 | 
  181 |     // 前序 spec 应已消费完故障注入；此处先释放可能的阻塞残留并确认网关干净
  182 |     await controlPost(request, '/__acceptance/gateway/release');
  183 |     const clean = await controlGet(request, '/__acceptance/gateway/status');
  184 |     expect(clean.block_remaining, '网关阻塞计数应为 0（前序 spec 未清理会污染本用例）').toBe(0);
  185 |     expect(clean.fail_remaining, '网关失败注入应为 0（前序 spec 未清理会污染本用例）').toBe(0);
  186 | 
  187 |     // 布好阻塞：下一次模型调用进入等待，为“生成期间发布新版本”创造时间窗
  188 |     const armed = await controlPost(request, '/__acceptance/gateway/block-next', { count: 1 });
  189 |     expect(armed.armed).toBe(1);
  190 | 
  191 |     // 新建会话，问文档型问题（Q27/D04，必然走到模型调用；doc-guide 已被 05 删除，不能用 Q25）
  192 |     await page.goto('/chat');
  193 |     await expect(page.locator('#welcome-title')).toBeVisible({ timeout: 30_000 });
  194 |     const before = await assistantCards(page).count();
  195 | 
  196 |     // 真实 UI 点击发送；不等待回答，先取证“在途”（此时不能用 askViaUi，它可能阻塞到回答完成）
  197 |     await page.locator('#question-input').fill(DOCUMENT_QUESTION);
  198 |     await page.getByRole('button', { name: '发送', exact: true }).click();
  199 |     await expect(page.locator('.typing')).toBeVisible({ timeout: 30_000 });
  200 | 
  201 |     // 后端模型调用必须已经进入阻塞（entered=true），证明更新发生在生成期间
  202 |     const entered = await waitForGatewayStatus(request, (state) => state.entered === true, 30_000);
  203 |     expect(entered.entered).toBe(true);
  204 |     await shot(page, 'a-21-01-question-in-flight');
  205 | 
  206 |     // 生成期间制造知识变更：把 V06 发布为 doc-stores 槽新版本（新电话）
  207 |     const phoneUpdate = await controlPost(request, '/__acceptance/scenario/update-phone');
  208 |     expect(phoneUpdate.applied).toBe(true);
  209 |     expect(phoneUpdate.new_value).toBe(NEW_PHONE);
  210 | 
  211 |     // 释放模型调用，让早先的 ask 走到提交阶段；提交时 revision 已变化 → knowledge_changed
  212 |     const release = await controlPost(request, '/__acceptance/gateway/release');
  213 |     expect(release.released).toBe(true);
  214 | 
  215 |     const card = await waitForSettledAnswer(page, before + 1);
  216 |     await expect(card.locator('.assistant-head .badge')).toHaveText('资料已更新');
> 217 |     await expect(card).toContainText('资料已更新，本次回答已中止，请重新查询。');
      |                        ^ Error: expect(locator).toContainText(expected) failed
  218 |     await expect(card).toContainText('回答生成期间资料版本发生变化');
  219 |     await expect(card.getByRole('button', { name: '重新查询' })).toBeVisible();
  220 | 
  221 |     // knowledge_changed 不得带来源（来源区块、来源条、查看依据按钮都不应存在）
  222 |     await expect(card.getByText('来源与依据')).toHaveCount(0);
  223 |     await expect(card.locator('.source-bar')).toHaveCount(0);
  224 |     await expect(card.getByText('查看依据')).toHaveCount(0);
  225 |     const cardText = await card.innerText();
  226 |     expect(cardText).not.toContain(NEW_PHONE); // 中止的回答不得泄露生成期间的新值
  227 |     await shot(page, 'a-21-02-knowledge-changed-no-sources');
  228 | 
  229 |     const after = await waitForGatewayStatus(
  230 |       request,
  231 |       (state) => state.entered === false && state.block_remaining === 0,
  232 |       15_000,
  233 |     );
  234 |     expect(after.block_remaining).toBe(0);
  235 |     const finalState = await acceptanceState(request);
  236 |     expect(finalState.scenarios.update_phone.applied).toBe(true);
  237 | 
  238 |     writeJson('acceptance-07-update/a21-knowledge-changed', {
  239 |       case: 'A-21',
  240 |       question: DOCUMENT_QUESTION,
  241 |       gateway: { entered, release, after },
  242 |       phone_update: {
  243 |         applied: phoneUpdate.applied,
  244 |         new_value: phoneUpdate.new_value,
  245 |         version_id: phoneUpdate.version_id,
  246 |         revision: phoneUpdate.revision,
  247 |       },
  248 |       message: {
  249 |         badge: await cardBadge(card),
  250 |         text: cardText,
  251 |         has_sources: (await card.locator('.source-bar').count()) > 0,
  252 |         has_source_section: (await card.getByText('来源与依据').count()) > 0,
  253 |         has_retry_button: (await card.getByRole('button', { name: '重新查询' }).count()) > 0,
  254 |       },
  255 |       outbound_external: finalState.outbound?.external ?? null,
  256 |     });
  257 |   });
  258 | });
  259 | 
```