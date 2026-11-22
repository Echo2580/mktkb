# T306 性能实测（只读、未建索引）

口径：进程内 sqlite3 只读连接，单查询 5 次取中位数/最大值；时间为毫秒；查询为 T302 主路径的等价形状，并非完整 API 端到端。

## T306 集成隔离库（受控种子）

| 窗口 | 窗口内请求行 | 总请求行 | 资料数 | 来源行 | 查询 | 中位 ms | 最大 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| today | 6 | 8 | 4 | 5 | overview_completed | 0.009 | 0.095 |
| today | 6 | 8 | 4 | 5 | requests_page | 0.012 | 0.044 |
| today | 6 | 8 | 4 | 5 | documents_citations | 0.012 | 0.097 |
| 7d | 8 | 8 | 4 | 5 | overview_completed | 0.008 | 0.012 |
| 7d | 8 | 8 | 4 | 5 | requests_page | 0.014 | 0.018 |
| 7d | 8 | 8 | 4 | 5 | documents_citations | 0.013 | 0.017 |
| 30d | 8 | 8 | 4 | 5 | overview_completed | 0.009 | 0.158 |
| 30d | 8 | 8 | 4 | 5 | requests_page | 0.014 | 0.016 |
| 30d | 8 | 8 | 4 | 5 | documents_citations | 0.013 | 0.016 |

EXPLAIN QUERY PLAN（7d）：

- `overview_completed`
  - USE TEMP B-TREE FOR count(DISTINCT)
  - SEARCH r USING INDEX ix_conversation_requests_status_deadline (status=?)
  - SEARCH c USING INDEX sqlite_autoindex_conversations_1 (id=?) LEFT-JOIN
- `requests_page`
  - SEARCH r USING INDEX ix_conversation_requests_status_deadline (status=?)
  - SEARCH c USING INDEX sqlite_autoindex_conversations_1 (id=?) LEFT-JOIN
  - USE TEMP B-TREE FOR ORDER BY
- `documents_citations`
  - SEARCH r USING INDEX ix_conversation_requests_status_deadline (status=?)
  - SEARCH m USING INDEX sqlite_autoindex_conversation_messages_1 (id=?)
  - SEARCH s USING INDEX ix_conversation_message_sources_message (message_id=?)
  - SEARCH c USING INDEX sqlite_autoindex_conversations_1 (id=?) LEFT-JOIN
  - USE TEMP B-TREE FOR GROUP BY
  - USE TEMP B-TREE FOR count(DISTINCT)
  - USE TEMP B-TREE FOR ORDER BY

## T301 隔离基准库（冻结只读）

| 窗口 | 窗口内请求行 | 总请求行 | 资料数 | 来源行 | 查询 | 中位 ms | 最大 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| today | 13 | 16 | 7 | 16 | overview_completed | 0.012 | 0.094 |
| today | 13 | 16 | 7 | 16 | requests_page | 0.026 | 0.071 |
| today | 13 | 16 | 7 | 16 | documents_citations | 0.043 | 0.105 |
| 7d | 15 | 16 | 7 | 16 | overview_completed | 0.012 | 0.016 |
| 7d | 15 | 16 | 7 | 16 | requests_page | 0.032 | 0.238 |
| 7d | 15 | 16 | 7 | 16 | documents_citations | 0.02 | 0.029 |
| 30d | 15 | 16 | 7 | 16 | overview_completed | 0.012 | 0.015 |
| 30d | 15 | 16 | 7 | 16 | requests_page | 0.028 | 0.031 |
| 30d | 15 | 16 | 7 | 16 | documents_citations | 0.019 | 0.022 |

EXPLAIN QUERY PLAN（7d）：

- `overview_completed`
  - USE TEMP B-TREE FOR count(DISTINCT)
  - SEARCH r USING INDEX ix_conversation_requests_status_deadline (status=?)
  - SEARCH c USING INDEX sqlite_autoindex_conversations_1 (id=?) LEFT-JOIN
- `requests_page`
  - SEARCH r USING INDEX ix_conversation_requests_status_deadline (status=?)
  - SEARCH c USING INDEX sqlite_autoindex_conversations_1 (id=?) LEFT-JOIN
  - USE TEMP B-TREE FOR ORDER BY
- `documents_citations`
  - SEARCH r USING INDEX ix_conversation_requests_status_deadline (status=?)
  - SEARCH m USING INDEX sqlite_autoindex_conversation_messages_1 (id=?)
  - SEARCH s USING INDEX ix_conversation_message_sources_message (message_id=?)
  - SEARCH c USING INDEX sqlite_autoindex_conversations_1 (id=?) LEFT-JOIN
  - USE TEMP B-TREE FOR GROUP BY
  - USE TEMP B-TREE FOR count(DISTINCT)
  - USE TEMP B-TREE FOR ORDER BY
