"""事实准入：结构化记录值、正文数据 token 与来源有效性校验。

设计目标：
- 记录型精确值由结构化证据生成，不依赖“位置是/放在”等有限句式；
- 伪造值、跨实体、跨字段角色、无引用、失效来源必须拒绝；
- 正确值旁边夹带无关值也要拒绝，不能只检查“正确子串存在”。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping

from ..retrieval.tokenize import normalize
from .chunking import ROLE_SYNONYMS, role_label
from .errors import CrossEntity, CrossField, FactRejected, ForgedValue, StaleSource, UnsupportedClaim
from .query import Lexicon
from .types import Fact, IndexedChunk, QueryPlan

_VALUE_TOKEN = re.compile(r"[0-9A-Za-z]+(?:[-_./:][0-9A-Za-z]+)*")
_ENTITY_ROLES = frozenset({"store", "item", "product", "channel", "price_type", "identifier", "alias"})
# 枚举行的稳定记录标记：由 doc/version/source unit 三元组派生，不依赖标题或行号。
_RECORD_REF = re.compile(r"（记录 ([0-9a-f]{8})）")


def record_reference(doc_id: str, version_id: str, unit_id: str) -> str:
    """来源单元的稳定短指纹：doc/version/unit 唯一，不含标题与行号。"""
    payload = f"{doc_id}|{version_id}|{unit_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:8]


class FactValidator:
    def __init__(self, index: Any, plan: QueryPlan, lexicon: Lexicon) -> None:
        self.index = index
        self.plan = plan
        self.lexicon = lexicon

    def validate_fact(self, fact: Fact, *, allow_all_roles: bool = False) -> None:
        chunk = self.index.get_chunk(fact.source_chunk_id, require_visible=True)
        if chunk is None:
            raise StaleSource("引用来源不存在或已失效")
        if chunk.version_id != fact.version_id:
            raise StaleSource("引用来源版本不一致")
        if chunk.doc_id != fact.doc_id:
            raise StaleSource("事实绑定的资料与引用块不一致")
        if fact.source_unit_id:
            unit = self.index.get_unit(fact.source_unit_id)
            if unit is None:
                raise StaleSource("事实绑定的原始单元不存在或已失效")
            if unit.doc_id != fact.doc_id or unit.version_id != fact.version_id:
                raise StaleSource("事实绑定的原始单元与资料/版本不一致")
            if chunk.record_unit_id and chunk.record_unit_id != fact.source_unit_id:
                raise StaleSource("事实绑定的原始单元与引用记录不一致")
            if not chunk.record_unit_id and fact.source_unit_id not in set(chunk.unit_ids or ()):
                raise StaleSource("事实绑定的原始单元不在引用正文块内")
        if self.index.revision() != fact.revision:
            raise StaleSource("引用来源不在当前有效修订")
        if chunk.entity_key != fact.entity_key:
            raise CrossEntity("事实实体与来源实体不一致")
        values = tuple(str(item) for item in (chunk.role_values.get(fact.field_role) or ()))
        if normalize(fact.value) not in {normalize(item) for item in values}:
            raise ForgedValue(f"字段 {fact.field_role} 的值未在来源中出现")
        requested = set(getattr(self.plan, "field_roles", ()) or ())
        if self.plan.field_role:
            requested.add(self.plan.field_role)
        requested.add("identifier")
        if allow_all_roles:
            # 全字段枚举打印整条记录的全部字段；代表事实可能落在实体字段（门店/商品）上，
            # 不能按“未请求字段”拒绝。值仍须在来源 role_values 中（上面已核对）。
            from .query import RECORD_FIELD_ROLES

            requested = set(ROLE_SYNONYMS) | set(RECORD_FIELD_ROLES) | set(_ENTITY_ROLES) | {"unit", "date"}
        if fact.field_role not in requested:
            raise CrossField("事实字段角色与问题不一致")
        for key, value in self.plan.filters.items():
            if key in _ENTITY_ROLES and chunk.filters_norm.get(key) != normalize(value):
                raise CrossEntity("事实来源不满足问题实体条件")
        if self.plan.as_of and not self.plan.include_future:
            if chunk.effective_from and chunk.effective_from > self.plan.as_of:
                raise StaleSource("引用来源尚未生效")
            if chunk.effective_to and chunk.effective_to < self.plan.as_of:
                raise StaleSource("引用来源已失效")

    def validate_facts(self, facts: Iterable[Fact], *, allow_all_roles: bool = False) -> None:
        for fact in facts:
            self.validate_fact(fact, allow_all_roles=allow_all_roles)

    def validate_record_text(
        self,
        text: str,
        facts: list[Fact],
        *,
        extra_tokens: Iterable[str] = (),
        allow_all_roles: bool = False,
        disclosure_entities: Iterable[str] = (),
        disclosure_complete: bool = False,
    ) -> None:
        """校验记录型答案。

        `disclosure_entities` 只接受“本次问题请求 + 核对确实无当前记录”的实体：
        校验器自己再核一次（必须在 plan 的请求集合里、且该实体在本问事实与引用
        记录里都没有值），不能靠调用方口头声明；`disclosure_complete` 要求调用方
        已确认结果完整覆盖（无分页、无截断），否则不允许写“未找到”。
        """
        self.validate_facts(facts, allow_all_roles=allow_all_roles)
        if not facts:
            raise UnsupportedClaim("没有可校验的事实")
        disclosure = self._verified_disclosure(disclosure_entities, facts, complete=disclosure_complete)
        cited_ids = {fact.source_chunk_id for fact in facts}
        chunks = self.index.chunks_by_ids(sorted(cited_ids), visible_only=True)
        if len(chunks) != len(cited_ids):
            raise StaleSource("部分引用来源已失效")
        allowed_roles = {fact.field_role for fact in facts} | (_ENTITY_ROLES - {"identifier"})
        if self.plan.field_role in ("price", "quantity"):
            allowed_roles = allowed_roles | {"unit"}
        if allow_all_roles:
            # 全字段枚举打印整条记录的所有字段，不能再按“未请求字段”拒绝。
            from .query import RECORD_FIELD_ROLES

            allowed_roles = set(ROLE_SYNONYMS) | set(RECORD_FIELD_ROLES) | _ENTITY_ROLES | {"unit", "date"}
        allowed_values = {normalize(fact.value) for fact in facts}
        # 实体标签可能自带标识（如“宣传海报（标识：QF23）”），它属于展示名而不是字段值。
        label_text = [normalize(value) for fact in facts for value in (fact.entity_label,) if value]
        cited_text = "\n".join(chunk.text for chunk in chunks)
        cited_fields = "\n".join(
            f"{name} {value}" for chunk in chunks for name, value in chunk.fields.items()
        )
        corpus = cited_text + "\n" + cited_fields
        # 记录标记由 doc/version/source unit 派生，属于本回答的稳定来源令牌，不当作业务值。
        record_refs = {record_reference(fact.doc_id, fact.version_id, fact.source_unit_id) for fact in facts}
        corpus_tokens = {token.casefold() for token in _VALUE_TOKEN.findall(corpus)}
        corpus_tokens.update(str(token).casefold() for token in extra_tokens if str(token))
        corpus_tokens.update(ref.casefold() for ref in record_refs)
        for token in _VALUE_TOKEN.findall(text):
            if token.casefold() not in corpus_tokens:
                raise ForgedValue(f"回答包含引用来源中不存在的数据值：{token}")
        normalized_text = normalize(text)
        allowed_labels = {
            normalize(value)
            for fact in facts
            for value in (fact.entity_label, fact.value, role_label(fact.field_role))
            if value
        }
        allowed_labels.update(normalize(name) for name in disclosure if normalize(name))
        for chunk in chunks:
            for role, values in chunk.role_values.items():
                if role in allowed_roles:
                    continue
                for value in values:
                    key = normalize(value)
                    if len(key) < 2:
                        continue
                    if (
                        _value_in_text(key, normalized_text)
                        and key not in allowed_values
                        and not any(key in label for label in label_text)
                    ):
                        raise CrossField(f"回答混入了未请求字段 {role} 的值")
        cited_field_corpus = normalize(
            "\n".join(str(value) for chunk in chunks for value in (chunk.fields or {}).values())
        )
        for label in self.lexicon.all_entity_labels():
            key = normalize(label)
            if len(key) >= 2 and key in normalized_text and key not in allowed_labels:
                if allow_all_roles and key in cited_field_corpus:
                    # 全字段枚举逐行打印引用记录自己的字段原值；该实体确实来自引用记录的字段值，
                    # 属于本记录展示而不是“混入其它实体”。行级值槽仍逐行绑定核对（见下）。
                    continue
                # 实体短语可能作为事实标签的一部分出现；只拒绝完全不在本问事实中的已知实体。
                if not any(key in normalize(value) for value in allowed_labels):
                    raise CrossEntity("回答混入了其它已知实体")
        unit_values: set[str] = set()
        for chunk in chunks:
            unit_values.update(str(value) for value in chunk.role_values.get("unit", ()) if value)
        self._assert_entity_value_binding(
            text, facts, extra_tokens=extra_tokens, disclosure=disclosure, allow_all_roles=allow_all_roles
        )
        self._assert_supported_tokens(
            text, corpus, allowed_labels, unit_values, extra_tokens, extra_support=record_refs
        )
        if not normalized_text:
            raise UnsupportedClaim("回答为空")

    def _verified_disclosure(
        self,
        names: Iterable[str],
        facts: list[Fact],
        *,
        complete: bool,
    ) -> tuple[str, ...]:
        """只允许“本次请求 + 确实无当前记录”的实体进入无记录披露行。"""
        requested: set[str] = set()
        for source in (
            getattr(getattr(self.plan, "state", None), "stores", ()) or (),
            getattr(self.plan, "missing_stores", ()) or (),
            getattr(self.plan, "unknown_stores", ()) or (),
        ):
            requested.update(normalize(str(item)) for item in source if str(item).strip())
        store_filter = str(self.plan.filters.get("store") or "")
        if store_filter:
            requested.add(normalize(store_filter))
        unknown_store = getattr(self.plan, "unknown_store", None)
        if unknown_store:
            requested.add(normalize(str(unknown_store)))
        verified: list[str] = []
        for name in names:
            label = str(name).strip()
            key = normalize(label)
            if not label or not key:
                continue
            if key not in requested:
                raise CrossEntity(f"披露的实体未被本次问题请求：{label}")
            if self._entity_has_records(key, facts):
                raise CrossEntity(f"披露的实体在本问记录中有值，不能称无记录：{label}")
            if label not in verified:
                verified.append(label)
        if verified and not complete:
            raise UnsupportedClaim("披露无记录实体前必须确认本次结果已完整覆盖")
        return tuple(verified)

    @staticmethod
    def _assert_disclosure_line(text: str, disclosure: Iterable[str]) -> None:
        """“未在资料中找到”行必须逐字等于本轮核实的披露清单，不能夹带其它实体。"""
        marker = "未在资料中找到"
        lines = [line.strip() for line in str(text).splitlines() if marker in line]
        if not lines:
            return
        names = [str(name).strip() for name in disclosure if str(name).strip()]
        if not names:
            raise CrossEntity("答案包含未经本问核实的“未找到”结论")
        expected = f"{marker}：" + "、".join(names) + "（该实体没有匹配记录）。"
        if len(lines) > 1 or lines[0] != expected:
            raise CrossEntity("“未找到”结论只能列出经核实的无记录实体")

    def _entity_has_records(self, key: str, facts: list[Fact]) -> bool:
        for fact in facts:
            if normalize(fact.entity_label or "") == key:
                return True
            chunk = self.index.get_chunk(fact.source_chunk_id, require_visible=True)
            if chunk is None:
                continue
            for value in chunk.role_values.get("store", ()):
                if normalize(str(value)) == key:
                    return True
            filtered = str(chunk.filters_norm.get("store") or "")
            if filtered and normalize(filtered) == key:
                return True
        return False

    def _assert_entity_value_binding(
        self,
        text: str,
        facts: list[Fact],
        *,
        extra_tokens: Iterable[str] = (),
        disclosure: Iterable[str] = (),
        allow_all_roles: bool = False,
    ) -> None:
        """实体行的值槽只认“该实体 + 该字段 + 实际事实值”。

        - `extra_tokens`（total/page/returned/next_page）只支持摘要行，**不进入实体行**；
        - 同一记录里的其它字段（identifier/位置/行号）与来源标题（当前V2）属于来源/元数据区，
          不能替代所问字段的业务值；
        - 全字段枚举（allow_all_roles）时该记录自己的字段值仍然合法，否则会误拒产品自产文本。
        """
        from .query import RECORD_FIELD_ROLES

        groups: dict[str, set[str]] = {}
        label_tokens: dict[str, set[str]] = {}
        row_index: list[tuple[str, str, str]] = []
        metadata: set[str] = set()
        ref_owner: dict[str, str] = {}
        for fact in facts:
            key = normalize(fact.entity_label or "")
            if not key:
                continue
            bucket = groups.setdefault(key, set())
            label_tokens.setdefault(key, set()).update(
                token.casefold() for token in _VALUE_TOKEN.findall(str(fact.entity_label or ""))
            )
            bucket.update(token.casefold() for token in _VALUE_TOKEN.findall(str(fact.value)))
            ref = record_reference(fact.doc_id, fact.version_id, fact.source_unit_id)
            if ref_owner.setdefault(ref, key) != key:
                raise CrossEntity("同一记录标记对应了多个实体事实")
            metadata.add(ref.casefold())
            chunk = self.index.get_chunk(fact.source_chunk_id, require_visible=True)
            if chunk is None:
                continue
            # 单位随值一起展示（如“5 元2瓶”），属于该记录的字段展示而不是外来数值。
            for unit in chunk.role_values.get("unit", ()):
                bucket.update(token.casefold() for token in _VALUE_TOKEN.findall(str(unit)))
            for source in (chunk.title, chunk.sheet, chunk.doc_id, *[str(value) for value in (chunk.locator or {}).values()]):
                metadata.update(token.casefold() for token in _VALUE_TOKEN.findall(source or ""))
            row_value = str((chunk.locator or {}).get("row") or chunk.row_number or "")
            if row_value:
                row_index.append((key, normalize(str(chunk.title or "")), row_value))
            if allow_all_roles:
                # 全字段枚举：该记录自己打印的全部字段值都属于本行值槽；字段名（表头）
                # 只是列标签，不是业务值，也允许出现在本行。
                for name, value in (chunk.fields or {}).items():
                    bucket.update(token.casefold() for token in _VALUE_TOKEN.findall(str(name)))
                    bucket.update(token.casefold() for token in _VALUE_TOKEN.findall(str(value)))
        if not groups:
            return
        summary_tokens = {str(token).strip().casefold() for token in extra_tokens if str(token).strip()}
        disclosure_keys = [normalize(str(name)) for name in disclosure if str(name).strip()]
        self._assert_disclosure_line(text, disclosure)
        for line in str(text).splitlines():
            normalized_line = normalize(line)
            ref_match = _RECORD_REF.search(line)
            if ref_match is not None:
                owner = ref_owner.get(ref_match.group(1))
                if owner is None:
                    raise CrossEntity("回答记录了本次事实之外的记录标记")
                matched = [owner]
                line = _RECORD_REF.sub("", line, count=1)
            else:
                matched = [key for key in groups if key and key in normalized_line]
                if not matched and allow_all_roles:
                    # 兼容旧文本：枚举行不带记录标记时按“标题+行号”回退，仅唯一命中才接受。
                    matched = [
                        key
                        for key, title, row_value in row_index
                        if title and title in normalized_line and f"第 {row_value} 行" in normalized_line
                    ]
            if len(set(matched)) > 1:
                raise CrossEntity("同一行混入了多个实体的事实，无法核对值归属")
            if not matched:
                if any(key and key in normalized_line for key in disclosure_keys):
                    for token in _VALUE_TOKEN.findall(line):
                        raise CrossEntity(f"无记录披露行不得携带数值：{token}")
                    continue
                # 摘要行：只允许页码头/尾里出现过的计数数字。
                for token in _VALUE_TOKEN.findall(line):
                    if token.casefold() not in summary_tokens:
                        raise CrossEntity(f"非实体摘要行出现未核实的数值：{token}")
                continue
            value_zone, source_tokens = _split_source_zone(line)
            for token in source_tokens:
                if token.casefold() not in metadata:
                    raise ForgedValue(f"来源区出现引用元数据之外的数值：{token}")
            allowed = groups[matched[0]]
            line_allowed = allowed | metadata | label_tokens.get(matched[0], set())
            for token in _VALUE_TOKEN.findall(value_zone):
                if token.casefold() not in line_allowed:
                    raise CrossEntity(f"回答把非本实体本字段的值挂到了 {matched[0]} 名下：{token}")
            # 值槽（最后一列之后）只认该实体该字段的事实值：页码/行号/来源标题数字即使出现在
            # 元数据里，也不能顶替业务值。
            tail = value_zone.rsplit("：", 1)[-1] if "：" in value_zone else ""
            for token in _VALUE_TOKEN.findall(tail):
                if token.casefold() not in allowed:
                    raise CrossEntity(f"值槽出现非本实体本字段的数值：{token}")

    @staticmethod
    def _assert_supported_tokens(
        text: str,
        corpus: str,
        allowed_labels: set[str],
        unit_values: Iterable[str] = (),
        extra_labels: Iterable[str] = (),
        *,
        extra_support: Iterable[str] = (),
    ) -> None:
        """记录型文本的实义 token 必须来自引用证据或数据字段派生展示词。"""
        from ..retrieval.tokenize import cut

        support = {token for token in cut(corpus) if len(token) >= 2}
        for label in allowed_labels:
            support.update(token for token in cut(label) if len(token) >= 2)
        for label in extra_labels:
            for token in cut(str(label)):
                if len(token) >= 2:
                    support.add(token)
        for value in extra_support:
            cleaned = str(value).strip()
            if cleaned:
                support.add(cleaned)
        for unit in unit_values:
            cleaned = str(unit).strip()
            if not cleaned:
                continue
            support.add(cleaned)
            if not cleaned.startswith("每"):
                support.add(f"每{cleaned}")
            support.update(token for token in cut(cleaned) if len(token) >= 2)
        scaffolding = {
            "根据",
            "资料",
            "位置",
            "数量",
            "价格",
            "日期",
            "备注",
            "联系人",
            "电话",
            "地址",
            "合作",
            "状态",
            "元",
            "每",
            "共",
            "条",
            "当前",
            "第",
            "页",
            "本页",
            "最后一页",
            "最后",
            "已到",
            "一页",
            "显示",
            "已",
            "全部",
            "还有",
            "更多",
            "可",
            "继续",
            "查看",
            "来源",
            "冲突",
            "未在",
            "找到",
            "缺失",
            "实体",
            "没有",
            "匹配",
            "记录",
            "存在",
            "多个",
            "有效值",
            "未",
            "按",
            "上传",
            "时间",
            "自动",
            "选择",
            "其一",
            "未记录",
            "字段",
            "在",
            "为",
            "是",
            "的",
            "了",
            "和",
            "与",
            "或",
            "及",
            "中",
            "该",
            "其",
            "本",
            "问",
            "事实",
            "引用",
            "证据",
            "拒绝",
            "回答",
            "共",
            "条",
            "当前",
            "第",
            "页",
            "本页",
            "最后一页",
            "最后",
            "已到",
            "一页",
            "显示",
            "已",
            "全部",
            "还有",
            "更多",
            "可",
            "继续",
            "查看",
        }
        for token in cut(text):
            if len(token) < 2 or token.isdigit():
                continue
            if token in support or token in scaffolding:
                continue
            raise UnsupportedClaim(f"回答包含引用证据之外的实义片段：{token}")

    def validate_document_text(self, text: str, evidence: Iterable[Any]) -> None:
        evidence_list = list(evidence)
        if not evidence_list:
            raise UnsupportedClaim("没有引用证据")
        corpus = "\n".join(str(getattr(item, "text", "") or "") for item in evidence_list)
        corpus_fields = "\n".join(
            f"{name} {value}"
            for item in evidence_list
            for name, value in dict(getattr(item, "fields", None) or {}).items()
        )
        corpus = corpus + "\n" + corpus_fields
        tokens = {token.casefold() for token in _VALUE_TOKEN.findall(corpus)}
        for token in _VALUE_TOKEN.findall(text):
            if token.casefold() not in tokens:
                raise ForgedValue(f"回答包含引用证据中不存在的数据值：{token}")
        normalized_text = normalize(text)
        allowed = normalize(corpus)
        for label in self.lexicon.all_entity_labels():
            key = normalize(label)
            if len(key) >= 2 and key in normalized_text and key not in allowed:
                raise CrossEntity("回答混入了引用证据之外的实体")
        # 正文回答至少要有问题/证据中的实义片段；全无重合视为无依据。
        from ..retrieval.tokenize import cut

        question_terms = {
            token
            for token in cut(self.plan.question)
            if len(token) >= 2 and token not in ("什么", "多少", "哪里", "怎么", "如何")
        }
        evidence_terms = {token for token in cut(corpus) if len(token) >= 2}
        if question_terms and not (question_terms & evidence_terms):
            raise UnsupportedClaim("回答与引用证据没有可核对的重合")
        if not normalized_text:
            raise UnsupportedClaim("回答为空")


_SOURCE_SEGMENT = re.compile(r"（来源：[^）]*）")


def _split_source_zone(line: str) -> tuple[str, list[str]]:
    """把“（来源：…）”段从行里拆出来，返回（剩余文本, 来源段数据 token）。"""
    tokens: list[str] = []
    for match in _SOURCE_SEGMENT.finditer(line):
        tokens.extend(_VALUE_TOKEN.findall(match.group(0)))
    return _SOURCE_SEGMENT.sub("", line), tokens


def _value_in_text(value: str, text: str) -> bool:
    """短数字按 token 边界匹配，避免“010”里的“10”被当成数量字段值。"""
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return re.search(rf"(?<![\d.]){re.escape(value)}(?![\d.])", text) is not None
    return value in text


def assert_visible(chunk_id: str, index: Any) -> IndexedChunk:
    chunk = index.get_chunk(chunk_id, require_visible=True)
    if chunk is None:
        raise StaleSource("来源已失效")
    return chunk
