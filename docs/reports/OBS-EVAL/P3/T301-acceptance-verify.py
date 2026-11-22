# T301 独立验收核对（项目经理）：以只读 SQL 直接核对工作包 B 交付的隔离库与文档数字。
# 不复用 B 的复算脚本；口径按任务书 §2 独立编写。只 SELECT，不写任何库。
from __future__ import annotations

import sqlite3
from pathlib import Path

P3 = Path(__file__).resolve().parent
BIZ = P3 / "T301-isolated" / "evidence" / "data" / "mktkb.sqlite3"
TRC = P3 / "T301-isolated" / "evidence" / "data" / "qa-traces.sqlite3"


def ro(p: Path) -> sqlite3.Connection:
    return sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)


biz = ro(BIZ)
trc = ro(TRC)
checks: list[tuple[str, object, object]] = []


def check(name: str, expected, sql: str, conn=biz, params=()):
    row = conn.execute(sql, params).fetchone()
    actual = row[0] if row and len(row) == 1 else row
    checks.append((name, expected, actual))


# 请求行 / 范围内 / 已完成（排除已删除会话；succeeded 且结果消息非空）
check("请求行总数", 16, "SELECT COUNT(*) FROM conversation_requests")
check("范围内请求(排除已删除会话)", 15,
      "SELECT COUNT(*) FROM conversation_requests r JOIN conversations c ON c.id=r.conversation_id "
      "WHERE c.deleted_at IS NULL")
check("已完成问答量(范围内)", 13,
      "SELECT COUNT(*) FROM conversation_requests r JOIN conversations c ON c.id=r.conversation_id "
      "WHERE c.deleted_at IS NULL AND r.status='succeeded' AND r.result_message_id IS NOT NULL")
check("client_request_id 去重数(范围内已完成)", 13,
      "SELECT COUNT(DISTINCT r.client_request_id) FROM conversation_requests r "
      "JOIN conversations c ON c.id=r.conversation_id "
      "WHERE c.deleted_at IS NULL AND r.status='succeeded' AND r.result_message_id IS NOT NULL")
check("未提交中断(范围内)", 2,
      "SELECT COUNT(*) FROM conversation_requests r JOIN conversations c ON c.id=r.conversation_id "
      "WHERE c.deleted_at IS NULL AND r.status IN ('running','failed','cancelled','expired')")

# 六类分布（范围内已完成，按结果消息 kind）
six_sql = (
    "SELECT m.kind, COUNT(*) FROM conversation_requests r "
    "JOIN conversations c ON c.id=r.conversation_id "
    "JOIN conversation_messages m ON m.id=r.result_message_id "
    "WHERE c.deleted_at IS NULL AND r.status='succeeded' GROUP BY m.kind ORDER BY m.kind"
)
six = dict(biz.execute(six_sql).fetchall())
checks.append(("六类分布", {"answer": 8, "clarification": 1, "conflict": 1,
                          "knowledge_changed": 1, "not_found": 1, "service_error": 1}, six))

# 引用：非冲突行（范围内）、两维去重、冲突行
src_scope = (
    "FROM conversation_message_sources s "
    "JOIN conversation_messages m ON m.id=s.message_id "
    "JOIN conversation_requests r ON r.result_message_id=m.id "
    "JOIN conversations c ON c.id=r.conversation_id "
    "WHERE c.deleted_at IS NULL AND r.status='succeeded' "
)
check("非冲突持久引用行(范围内)", 13,
      "SELECT COUNT(*) " + src_scope + "AND m.kind != 'conflict'")
check("文档维去重对(消息+文档,非冲突)", 6,
      "SELECT COUNT(*) FROM (SELECT DISTINCT s.message_id, s.document_id " + src_scope +
      "AND m.kind != 'conflict')")
check("版本维去重对(消息+版本,非冲突)", 6,
      "SELECT COUNT(*) FROM (SELECT DISTINCT s.message_id, s.version_id " + src_scope +
      "AND m.kind != 'conflict')")
check("冲突消息持久引用行(D5 实测)", 2,
      "SELECT COUNT(*) FROM conversation_message_sources s "
      "JOIN conversation_messages m ON m.id=s.message_id WHERE m.kind='conflict'")
check("S05 冲突消息引用行数", 2,
      "SELECT COUNT(*) FROM conversation_message_sources WHERE message_id IN (?,?)",
      params=("f64d7637-78d8-4907-8271-5637c37aa801", "f64d763778d8490782715637c37aa801"))

# 库存：待审核版本 / 失败导入
check("待审核版本数", 1, "SELECT COUNT(*) FROM document_versions WHERE state='review_required'")
check("失败导入任务数", 1, "SELECT COUNT(*) FROM import_jobs WHERE state IN ('failed','blocked')")
check("失败任务错误码", "PARSE_INCOMPLETE",
      "SELECT error_code FROM import_jobs WHERE state IN ('failed','blocked')")

# 午夜边界（Asia/Shanghai = UTC+8）；先断言样本请求行存在，再核归属日
check("S17 请求行存在", 1,
      "SELECT COUNT(*) FROM conversation_requests WHERE id IN (?,?)",
      params=("dbc296bc-a471-45ba-a70d-5d4c21902332", "dbc296bca47145baa70d5d4c21902332"))
check("S18 请求行存在", 1,
      "SELECT COUNT(*) FROM conversation_requests WHERE id IN (?,?)",
      params=("c73f5013-dee9-4ee8-8a41-42b321e364dd", "c73f5013dee94ee88a4142b321e364dd"))
check("S17 归属日", "2026-11-20",
      "SELECT date(finished_at,'+8 hours') FROM conversation_requests WHERE id IN (?,?)",
      params=("dbc296bc-a471-45ba-a70d-5d4c21902332", "dbc296bca47145baa70d5d4c21902332"))
check("S18 归属日", "2026-11-21",
      "SELECT date(finished_at,'+8 hours') FROM conversation_requests WHERE id IN (?,?)",
      params=("c73f5013-dee9-4ee8-8a41-42b321e364dd", "c73f5013dee94ee88a4142b321e364dd"))

# Trace：总数 / 重放 / 覆盖 / 关闭态 / 未记录
check("Trace 总数", 12, "SELECT COUNT(*) FROM traces", conn=trc)
check("重放 Trace 数", 1, "SELECT COUNT(*) FROM traces WHERE replayed=1", conn=trc)
check("重放 Trace Span 数", 0,
      "SELECT COUNT(*) FROM spans s JOIN traces t ON t.trace_id=s.trace_id WHERE t.replayed=1", conn=trc)
# 跨库覆盖数：普通 Trace 的 request_id 集合 × 范围内已完成请求集合（统一去连字符比较）
norm = lambda s: s.replace("-", "")
normal_req = {norm(r[0]) for r in trc.execute("SELECT DISTINCT request_id FROM traces WHERE replayed=0")}
completed_ids = [norm(r[0]) for r in biz.execute(
    "SELECT r.id FROM conversation_requests r JOIN conversations c ON c.id=r.conversation_id "
    "WHERE c.deleted_at IS NULL AND r.status='succeeded' AND r.result_message_id IS NOT NULL")]
covered = len(set(completed_ids) & normal_req)
checks.append(("覆盖请求数(普通 Trace,范围内已完成)", 10, covered))
check("S15 请求行存在", 1,
      "SELECT COUNT(*) FROM conversation_requests WHERE id IN (?,?)",
      params=("600161b5-1939-4b6e-bd67-2e63f9f1a2e6", "600161b519394b6ebd672e63f9f1a2e6"))
check("S15 关闭态无 Trace 行", 0,
      "SELECT COUNT(*) FROM traces WHERE request_id IN (?,?)", conn=trc,
      params=("600161b5-1939-4b6e-bd67-2e63f9f1a2e6", "600161b519394b6ebd672e63f9f1a2e6"))
check("S17/S18 未记录(无 Trace)", 0,
      "SELECT COUNT(*) FROM traces WHERE request_id IN (?,?,?,?)", conn=trc,
      params=("dbc296bc-a471-45ba-a70d-5d4c21902332", "dbc296bca47145baa70d5d4c21902332",
              "c73f5013-dee9-4ee8-8a41-42b321e364dd", "c73f5013dee94ee88a4142b321e364dd"))

# 三路径均被观测
paths = {r[0] for r in trc.execute("SELECT DISTINCT path FROM traces").fetchall()}
checks.append(("三路径覆盖", {"rag", "legacy", "legacy_with_rag_candidates"}, paths))

biz.close()
trc.close()

ok = True
for name, expected, actual in checks:
    passed = expected == actual
    ok = ok and passed
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: 预期={expected} 实测={actual}")
print("RESULT:", "ALL-PASS" if ok else "HAS-FAIL")