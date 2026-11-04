"""企业模拟语料的表格数据（供 tools/build_enterprise_corpus.py 使用，不是产品代码）。"""

from __future__ import annotations

import random
from datetime import date, timedelta

from enterprise_corpus_data import (
    CHANNELS,
    CHECK_ITEMS,
    DATES,
    DEALERS,
    KPI_CATALOG,
    MATERIALS,
    POSITIONS,
    PRICE_PLANS,
    PURPOSES,
    SKUS,
    STORES,
    STORE_EXTRA_NAMES,
    fmt_day,
    pick_person,
)

SEED = 20261101
HEADER_ROW = 7


def _rng(salt: int) -> random.Random:
    return random.Random(SEED + salt)


def _sheet(name: str, preamble: list[str], header: list[str], rows: list[list], freeze_note: str = "") -> dict:
    body = [[cell] for cell in preamble]
    body += [[] for _ in range(max(0, HEADER_ROW - 2 - len(preamble)))]
    body.append(header)
    body.extend([list(row) for row in rows])
    if freeze_note:
        body.append([])
        body.append([freeze_note])
    return {"name": name, "rows": body}


# --------------------------------------------------------------------- 位置与主数据


def positions_rows() -> list[list]:
    out = []
    for pid, store, item, alias, loc, qty, unit, updated in POSITIONS:
        out.append([pid, store, item, alias, loc, qty, unit, updated])
    return out


def positions_sheet() -> dict:
    return _sheet(
        "物品位置",
        [
            "启沣饮品（苏城）市场部 终端物料位置表",
            "文件编号：QF-SCB-2026-018 V2",
            "编制：通路行销组 复核：王岚 批准：沈亮",
            f"业务更新日期：{fmt_day(DATES['biz_base'])}（模拟语料，非真实企业数据）",
            "填写说明：位置精确到区、货架/柜号和层位；临时调整需在24小时内回写本表。",
        ],
        ["标识", "门店", "物品", "别名", "位置", "数量", "单位", "更新日期"],
        positions_rows(),
        freeze_note="本表为市场部内部台账模拟样本，历史版本见《终端物料位置表（历史V1）》。",
    )


def materials_sheet() -> dict:
    header = [
        "物料编码", "物料名称", "物料分类", "规格型号", "基本单位", "包装换算", "商品条码",
        "品牌/口味", "保质期天数", "存储条件", "是否批次管理", "适用渠道", "参考供价",
        "建议零售价", "默认仓库", "生命周期状态", "创建日期",
    ]
    rows = []
    for r in SKUS:
        rows.append([
            r["code"], r["name"], "成品-饮料", r["spec"], "罐" if "罐" in r["spec"] else "瓶",
            r["case"], r["barcode"], r["name"].split("（")[0], r["shelf_days"], "常温避光", "是",
            "NKA卖场|LKA连锁|CVS便利店|特通|线上O2O", r["supply"], r["msrp"], "CK01苏城中心仓",
            "启用", "2026-01-08",
        ])
    for m in MATERIALS:
        rows.append([
            m["code"], m["name"], m["type"], m["spec"], m["unit"], "—", "—", "启沣", "—",
            "常温避光", "否", "全渠道", m["unit_price"], "—", "CK02物料仓", "启用", "2026-02-16",
        ])
    return _sheet(
        "物料主数据",
        ["启沣饮品（苏城）有限公司 物料与成品主数据表", "维护部门：市场部通路行销组",
         "文件编号：QF-SCB-2026-006 V1", f"数据截止：{fmt_day(DATES['biz_base'])}",
         "说明：成品条码为 69 开头的 13 位 EAN-13 模拟编码，不指向任何真实商品。"],
        header, rows,
        freeze_note="广宣物料单价为印制成本价，用于费用核销与赔偿计算。",
    )


def stores_sheet() -> dict:
    header = [
        "门店编码", "门店名称", "所属大区", "城市片区", "渠道类型", "门店等级", "经营面积(㎡)",
        "日均客流(人次)", "所属经销商", "店长", "联系电话", "详细地址", "开业日期", "状态",
    ]
    rng = _rng(11)
    rows = []
    for code, name, region, city, channel, level, area, traffic, dealer, principal, phone, addr, opened, status in STORES:
        rows.append([code, name, region, city, channel, level, area, traffic, dealer, principal,
                     phone, addr, opened, status])
    for i, name in enumerate(STORE_EXTRA_NAMES, start=len(STORES)):
        rows.append([
            f"MD-SC-{1000 + i}", name, "华东事业部", rng.choice(["苏城市城东", "苏城市城西", "苏城市城南", "苏城市城北", "苏城市经开"]),
            rng.choice(CHANNELS), rng.choice(["A", "B", "B", "C"]), rng.randint(60, 1800),
            rng.randint(300, 12000), rng.choice(DEALERS)["name"], pick_person(rng),
            f"0512-8{rng.randint(1000000, 9999999)}", f"苏城市{rng.choice(['启沣路', '宏泽街', '安平路', '礼嘉街'])}{rng.randint(1, 300)}号",
            fmt_day(date(2020 + rng.randint(0, 5), rng.randint(1, 12), rng.randint(1, 28))),
            rng.choice(["营业", "营业", "营业", "筹备", "停业"]),
        ])
    return _sheet(
        "门店主数据",
        ["启沣饮品（苏城）市场部 覆盖门店台账", "文件编号：QF-SCB-2026-007 V3",
         f"统计口径：{fmt_day(DATES['q4_start'])} 有效在册门店", "说明：门店名称、电话、地址均为模拟值。"],
        header, rows,
        freeze_note="状态为停业的门店不参与陈列达标率与物料覆盖率考核。",
    )


# --------------------------------------------------------------------- 价格、陈列、台账


def price_sheets() -> list[dict]:
    header = [
        "价格单号", "SKU编码", "品名规格", "适用渠道", "适用区域", "价格类型", "价格(元)", "计价单位",
        "搭赠/限购规则", "生效日期", "失效日期", "审批编号", "状态",
    ]
    sheets = []
    for channel in ["NKA卖场", "LKA连锁", "CVS便利店", "特通", "流通二批", "线上O2O"]:
        rows = []
        for idx, (sku_code, ctype, ptype, price, unit, rule, start, end, sp_no, status) in enumerate(PRICE_PLANS):
            if ctype != channel:
                continue
            sku = next(s for s in SKUS if s["code"] == sku_code)
            rows.append([
                f"PX-{idx + 1:04d}", sku_code, f"{sku['name']} {sku['spec']}", channel, "华东事业部（苏城市）",
                ptype, price, unit, rule, fmt_day(start), fmt_day(end), sp_no, status,
            ])
        sheets.append(_sheet(
            channel,
            [f"2026年Q4渠道价目表（{channel}）", "文件编号：QF-SCB-2026-012 V4",
             f"生效区间：{fmt_day(DATES['q4_start'])} 起，未标失效者为长期执行",
             "取价优先级：促销价 → 会员价 → 门店零售价 → 建议零售价。",
             "说明：本表为模拟价格，不得用于实际报价或合同。"],
            header, rows,
            freeze_note="跨区串货按《经销商合作协议要点》第 7 条处理。",
        ))
    return sheets


def display_sheet() -> dict:
    header = [
        "标准编号", "适用渠道", "门店等级", "位置类型", "货架/位编号", "层位", "标准排面数(面)",
        "SKU上限", "对应物料编码", "物料数量", "摆放要求", "翻新周期", "考核分值", "扣分规则", "生效期间",
    ]
    rng = _rng(23)
    rows = []
    loc_types = ["货架层板", "端架", "堆头", "包柱", "收银台", "吊旗", "灯箱", "冰柜贴", "货架卡", "地贴"]
    levels = ["A", "B", "C"]
    seq = 1
    for channel in CHANNELS:
        for level in levels:
            for loc in loc_types:
                if rng.random() < 0.45:
                    continue
                mat = rng.choice(MATERIALS)
                rows.append([
                    f"DS-2026-{seq:03d}", channel, level, loc,
                    f"{'H' if loc in ('货架层板', '货架卡') else ('TG' if loc == '堆头' else 'E')}-{rng.randint(1, 24):02d}",
                    rng.choice(["第一层", "第二层", "第三层（黄金位1.2-1.5m）", "底层", "顶端", "—"]),
                    rng.choice([2, 2, 3, 4, 6]), rng.choice([1, 2, 2, 3]), mat["code"], rng.randint(1, 12),
                    rng.choice(["垂直陈列、正面向外、丰满度≥80%", "先进先出、下大上小", "整箱割箱堆码，高度≤1.4m",
                                "与价签一一对应，不得遮挡消防通道"]),
                    rng.choice(["1周", "2周", "1个月"]), rng.choice([5, 6, 8, 10]),
                    rng.choice(["缺1面扣2分", "无POP扣1分", "位置错误扣3分", "过期未撤扣5分"]),
                    f"{fmt_day(DATES['q4_start'])} 起",
                ])
                seq += 1
    return _sheet(
        "陈列标准",
        ["终端陈列与生动化执行标准（2026年Q4）", "文件编号：QF-SCB-2026-003 V2.1",
         "依据：《终端陈列与生动化管理制度》第五章", f"生效日期：{fmt_day(DATES['publish_effect'])}",
         "说明：黄金陈列位指距地面 1.2–1.5 米的视线水平层。"],
        header, rows,
        freeze_note="同一门店端架与堆头合计不超过 2 个 SKU，超出部分按陈列奖励不予结算。",
    )


def ledger_sheets() -> list[dict]:
    rng = _rng(31)
    header = [
        "申请单号", "申请日期", "领用日期", "门店编码", "门店名称", "物料编码", "物料名称", "规格",
        "申请数量", "实发数量", "单位", "领用人", "用途", "关联活动号", "单价(元)", "金额(元)",
        "核销状态", "核销日期", "核销人", "库存地点", "备注",
    ]
    rows = []
    day = DATES["q3_start"]
    for i in range(1200):
        store = rng.choice(STORES[:18]) if rng.random() < 0.6 else rng.choice(STORES)
        mat = rng.choice(MATERIALS)
        apply_day = day + timedelta(days=rng.randint(0, 88))
        got_day = apply_day + timedelta(days=rng.randint(1, 6))
        qty = rng.randint(5, 200)
        real = qty if rng.random() < 0.75 else max(1, qty - rng.randint(1, 6))
        price = mat["unit_price"]
        status = rng.choice(["已核销", "已核销", "待核销", "部分核销", "退回", "报废"])
        settle = got_day + timedelta(days=rng.randint(3, 20)) if status in ("已核销", "部分核销") else None
        rows.append([
            f"LY-2026-{1000 + i}", fmt_day(apply_day), fmt_day(got_day), store[0], store[1], mat["code"],
            mat["name"], mat["spec"], qty, real, mat["unit"], pick_person(rng), rng.choice(PURPOSES),
            f"ACT-2026-{rng.randint(1, 48):03d}", price, round(real * price, 2), status,
            fmt_day(settle) if settle else "—", pick_person(rng) if settle else "—",
            rng.choice(["CK01苏城中心仓", "CK02物料仓", "CK03华中仓"]),
            rng.choice(["正常领用", "补货", "档期更换", "破损补发", "首批铺市"]),
        ])
    main = _sheet(
        "领用核销台账",
        ["启沣饮品（苏城）市场部 广宣物料领用与核销台账（2026Q3）", "文件编号：QF-SCB-2026-015",
         f"区间：{fmt_day(DATES['q3_start'])} 至 {fmt_day(DATES['q3_end'])}，共 1200 行",
         "规则：促销活动结束后 6 个自然日内上交结案凭证；台账金额按实发数量计。"],
        header, rows,
        freeze_note="台账数据为模拟流水，用于测试检索与批量表格解析，不构成任何财务依据。",
    )

    inspect_header = [
        "巡检单号", "巡检日期", "门店编码", "门店名称", "检查人", "大类", "题项编号", "检查项",
        "标准分", "实得分", "是否合格", "扣分原因", "问题等级", "整改责任人", "整改期限", "整改动作",
        "复检日期", "复检结果",
    ]
    irows = []
    for i in range(2000):
        code, name = rng.choice(STORES[:20])[0], rng.choice(STORES[:20])[1]
        check = rng.choice(CHECK_ITEMS)
        std = rng.choice([4, 6, 6, 8, 10])
        lost = rng.choice([0, 0, 0, 1, 2, 3, std // 2])
        got = max(0, std - lost)
        ok = got >= std * 0.8
        level = "合格" if ok else rng.choice(["一般", "一般", "重大", "红线"])
        visit = DATES["q3_start"] + timedelta(days=rng.randint(0, 90))
        rows_extra = "" if ok else rng.choice(["端架缺2面", "价签被遮挡", "物料过期未撤", "堆头高度超限", "排面丰满度不足", "本品与竞品混放"])
        irows.append([
            f"XJ-{visit.strftime('%Y%m%d')}-{i:04d}", fmt_day(visit), code, name, pick_person(rng),
            check["cat"], check["code"], check["item"], std, got, "是" if ok else "否", rows_extra or "—",
            level, "—" if ok else pick_person(rng),
            "—" if ok else rng.choice(["24小时", "48小时", "72小时"]),
            "—" if ok else rng.choice(["补齐排面", "更换物料", "重新标价", "撤除过期POP", "整理堆头"]),
            fmt_day(visit + timedelta(days=rng.randint(1, 5))) if not ok else "—",
            rng.choice(["通过", "通过", "未通过", "升级"]) if not ok else "—",
        ])
    inspection = _sheet(
        "巡检评分明细",
        ["终端巡检评分明细（2026Q3，共 2000 行）", "依据：《门店巡检与评分管理办法》QF-SCB-2026-011 V2",
         "口径：100 分制，单项实得分低于标准分 80% 记不合格；总分 <85 分开整改单。",
         f"检查周期：{fmt_day(DATES['q3_start'])} 至 {fmt_day(DATES['q3_end'])}",
         "整改时限：一般问题 48 小时，重大问题 24 小时，红线问题立即停业整改。"],
        inspect_header, irows,
    )

    gift_header = ["核销单号", "活动编号", "门店名称", "赠品编码", "赠品名称", "发放数量", "发放日期",
                   "凭证类型", "照片张数", "销量拉单(元)", "核销金额(元)", "稽核结论", "稽核日期"]
    grows = []
    for i in range(800):
        act = f"ACT-2026-{rng.randint(1, 48):03d}"
        gives = [m for m in MATERIALS if m["type"] == "赠品"] or MATERIALS
        g = rng.choice(gives)
        issue = DATES["q3_start"] + timedelta(days=rng.randint(0, 92))
        verdict = rng.choice(["属实", "属实", "属实", "部分属实", "不属实"])
        grows.append([
            f"HX-2026-{5000 + i}", act, rng.choice(STORES)[1], g["code"], g["name"], rng.randint(10, 400),
            fmt_day(issue), rng.choice(["现场照片+签收单", "现场照片", "签收单", "销量系统拉单"]),
            rng.choice([3, 5, 5, 6]), round(rng.uniform(200, 9000), 2),
            round(rng.uniform(50, 1200), 2), verdict,
            fmt_day(issue + timedelta(days=rng.randint(4, 25))),
        ])
    gift = _sheet(
        "赠品核销明细",
        ["买赠活动赠品发放与核销明细（2026Q3）", "文件编号：QF-SCB-2026-021",
         "依据：《市场督察与费用稽核规定》第三章", "每场活动照片不得少于 5 张，缺失照片按不属实处理。"],
        gift_header, grows,
    )
    return [main, inspection, gift]


def campaign_sheet() -> dict:
    header = ["活动编号", "活动名称", "活动类型", "机制", "适用渠道", "参与门店数", "开始日期", "结束日期",
              "预算(元)", "实际费用(元)", "负责人", "状态", "结案日期", "备注"]
    rng = _rng(41)
    rows = []
    kinds = ["买赠", "特价", "满减", "试饮", "路演", "陈列奖励", "组合价", "会员价"]
    for i in range(80):
        start = DATES["q3_start"] + timedelta(days=rng.randint(0, 150))
        end = start + timedelta(days=rng.choice([7, 10, 14, 21, 28]))
        budget = rng.choice([8000, 15000, 26000, 42000, 68000, 120000])
        kind = rng.choice(kinds)
        closed = rng.random() < 0.7
        rows.append([
            f"ACT-2026-{i + 1:03d}", f"{start.month}月{rng.choice(['夏季冰饮', '开学季', '国庆档', '双11预热', '年货节', '乌龙茶主推', '无糖茶铺市'])}{kind}活动",
            kind, rng.choice(["满5件送围裙1件", "满200减50", "特价2.99元限购4瓶", "第二件半价",
                              "买1箱赠6瓶", "试饮100杯送50杯", "端架陈列奖励600元/月", "5.00元/2瓶组合价"]),
            rng.choice(CHANNELS), rng.randint(6, 240), fmt_day(start), fmt_day(end), budget,
            round(budget * rng.uniform(0.62, 1.18), 2), pick_person(rng),
            rng.choice(["已结案", "执行中", "待审批", "暂停"]) if not closed else "已结案",
            fmt_day(end + timedelta(days=rng.randint(3, 12))) if closed else "—",
            rng.choice(["需补照片", "凭证齐全", "跨区串货已通报", "费用率超 8% 需说明", "—"]),
        ])
    return _sheet(
        "活动排期",
        ["2026 年市场部促销活动排期与结案台账", "文件编号：QF-SCB-2026-019",
         "规则：KA 渠道费用须提前 60 天申请；活动结束 6 个自然日内结案。",
         f"促销费用率红线：8%（超出须事业部总经理批准）"],
        header, rows,
    )


def dealer_sheet() -> dict:
    header = ["经销商编码", "经销商名称", "覆盖区域", "覆盖门店数", "合作起始", "账期类型", "账期天数",
              "月返比例", "季返达量比例", "回款及时率", "评级", "状态"]
    rng = _rng(53)
    rows = []
    for i, d in enumerate(DEALERS):
        rows.append([
            d["code"], d["name"], d["region"], rng.randint(8, 320), f"20{rng.randint(14, 24)}-{rng.randint(1, 12):02d}-01",
            d["term_type"], d["term_days"], f"{rng.choice([2, 3, 3, 4])}%", f"{rng.choice([0.5, 1, 1])}%",
            f"{rng.uniform(0.82, 0.99):.1%}", rng.choice(["A", "A", "B", "B", "C"]),
            "合作中" if i % 9 else "暂停",
        ])
    return _sheet(
        "经销商名录",
        ["启沣饮品（苏城）经销商与通路覆盖名录", "文件编号：QF-SCB-2026-022",
         f"口径截至：{fmt_day(DATES['biz_base'])}", "说明：名称与比例为模拟值。"],
        header, rows,
    )


def kpi_sheet() -> dict:
    header = ["月份", "指标", "计算口径", "目标", "实际", "达成率", "同比", "负责人"]
    rng = _rng(61)
    rows = []
    for month in range(1, 11):
        for k in KPI_CATALOG:
            target = k["target"]
            actual = round(target * rng.uniform(0.78, 1.15), 1) if k["unit"] == "%" else round(target * rng.uniform(0.78, 1.15))
            rate = actual / target
            rows.append([
                f"2026-{month:02d}", k["name"], k["formula"], f"{target}{k['unit']}", f"{actual}{k['unit']}",
                f"{rate:.1%}", f"{rng.uniform(-0.18, 0.29):+.1%}", pick_person(rng),
            ])
    return _sheet(
        "KPI月报",
        ["市场部核心 KPI 月度报表（2026年1–10月）", "文件编号：QF-SCB-2026-024",
         "口径以《终端陈列与生动化管理制度》第六章与《门店巡检与评分管理办法》为准。",
         "注意：达成率与同比为模拟数据。"],
        header, rows,
    )


def contact_history_sheet() -> dict:
    header = ["门店编码", "门店名称", "变更字段", "旧值", "新值", "生效日期", "依据通知编号", "经办人", "当前是否有效"]
    rng = _rng(71)
    rows = []
    for idx, (code, name, *_rest) in enumerate(STORES):
        kind = idx % 3
        if kind == 0:
            old, new = f"0512-8{rng.randint(1000000, 9999999)}", f"0512-8{rng.randint(1000000, 9999999)}"
            field = "联系电话"
        elif kind == 1:
            old, new, field = pick_person(rng), pick_person(rng), "联系人"
        else:
            old = f"苏城市启沣路{rng.randint(1, 90)}号"
            new = f"苏城市宏泽街{rng.randint(1, 90)}号"
            field = "地址"
        effect = DATES["q3_start"] + timedelta(days=rng.randint(0, 150))
        rows.append([code, name, field, old, new, fmt_day(effect), f"启市字〔2026〕{rng.randint(20, 90)}号",
                     pick_person(rng), "是" if effect <= DATES["biz_base"] else "否（未生效）"])
    return _sheet(
        "门店信息变更",
        ["合作门店联系信息变更历史表", "文件编号：QF-SCB-2026-025 V2",
         "规则：门店电话/联系人变更以最新生效记录为准，历史值仅用于对账追溯。",
         f"截至 {fmt_day(DATES['biz_base'])} 共 {len(rows)} 条变更。"],
        header, rows,
    )
