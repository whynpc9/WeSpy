#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers for generating a lightweight daily brief from synced article metadata."""

import re
from collections import OrderedDict

SECTION_ORDER = [
    "政策规范",
    "招标采购信息",
    "研究论文",
    "会议讲座",
    "产品发布/企业动态",
    "行业观察/评论",
    "其他",
]

SUMMARY_NOISE_PATTERNS = [
    r"欢迎关注",
    r"扫码",
    r"联系我们",
    r"推荐阅读",
    r"免责声明",
    r"广告合作",
]

SUMMARY_PRIORITY_PATTERNS = [
    (r"明确|要求|提出|印发|发布|出台|规范|方案|办法|通知", 5),
    (r"支付改革|医保支付|数据互通|平台建设|标准接口|落地要求|执行路径", 5),
    (r"研究|论文|试验|结果显示|发现", 4),
    (r"会议|论坛|讲座|报名|峰会|年会", 3),
    (r"时间|日期|截至|范围|对象|开展|启动", 2),
]

SUMMARY_DEPRIORITIZE_PATTERNS = [
    r"本文系",
    r"现场报道",
    r"记者观察",
    r"导读",
    r"编者按",
]


def classify_article_title(title):
    text = (title or "").strip()
    lowered = text.lower()
    if any(keyword in text for keyword in ["医保局", "通知", "印发", "发布", "规范", "办法", "方案", "政策", "新规"]):
        if "招标" not in text and "采购" not in text:
            return "政策规范"
    if any(keyword in text for keyword in ["招标", "采购", "中标", "项目", "建设项目"]):
        return "招标采购信息"
    if any(keyword in text for keyword in ["论文", "研究", "发表于", "样本", "试验"]) or "nature" in lowered:
        return "研究论文"
    if any(keyword in text for keyword in ["会议", "论坛", "讲座", "直播", "报名", "峰会", "年会", "沙龙"]):
        return "会议讲座"
    if any(keyword in text for keyword in ["发布会", "新品", "合作", "布局", "平台", "解决方案", "产品"]):
        return "产品发布/企业动态"
    if any(keyword in text for keyword in ["观察", "解读", "评论", "周报", "盘点", "汇总", "速览"]):
        return "行业观察/评论"
    return "其他"


def normalize_title_for_dedupe(title):
    text = (title or "").strip()
    text = re.sub(r"（[^）]*）", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[|｜丨:].*$", "", text)
    text = re.sub(r"[：:].*$", "", text) if text.endswith("解读") else text
    text = re.sub(r"（解读）$", "", text)
    text = re.sub(r"解读$", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def source_priority(source_account):
    account = (source_account or "").strip()
    if "国家医保局" in account:
        return 120
    if any(keyword in account for keyword in ["国家卫生健康委", "国家卫健委"]):
        return 115
    if "中国医疗保障" in account:
        return 110
    if any(keyword in account for keyword in ["CHIMA", "中国医院", "国家"]):
        return 80
    return 50


def _dedupe_rows(rows):
    selected = OrderedDict()
    for row in rows:
        normalized = normalize_title_for_dedupe(row.get("title"))
        existing = selected.get(normalized)
        if existing is None:
            selected[normalized] = row
            continue
        current_priority = (source_priority(row.get("nickname")), int(row.get("create_time") or 0))
        existing_priority = (source_priority(existing.get("nickname")), int(existing.get("create_time") or 0))
        if current_priority > existing_priority:
            selected[normalized] = row
    return list(selected.values())


def _sentence_priority(sentence):
    positive_score = sum(
        weight for pattern, weight in SUMMARY_PRIORITY_PATTERNS if re.search(pattern, sentence, re.IGNORECASE)
    )
    negative_score = sum(
        3 for pattern in SUMMARY_DEPRIORITIZE_PATTERNS if re.search(pattern, sentence, re.IGNORECASE)
    )
    return positive_score - negative_score


def _sentence_topics(sentence):
    topic_patterns = {
        "policy_action": r"明确|要求|提出|印发|发布|出台|规范|方案|办法|通知",
        "core_topic": r"支付改革|医保支付|数据互通|平台建设|标准接口|落地要求|执行路径",
        "impact_scope": r"影响|执行安排|范围|对象|时间|日期|截至|启动|开展",
        "research": r"研究|论文|试验|结果显示|发现",
        "event": r"会议|论坛|讲座|报名|峰会|年会",
    }
    return {name for name, pattern in topic_patterns.items() if re.search(pattern, sentence, re.IGNORECASE)}


def _sentence_signal_labels(sentence):
    signal_patterns = {
        "policy_release": r"发布|印发|出台|通知",
        "payment_reform": r"支付改革|医保支付",
        "data_interop": r"数据互通",
        "platform_construction": r"平台建设|信息平台建设",
        "standard_interface": r"标准接口",
        "execution_path": r"执行路径|落地要求",
        "impact_execution": r"影响|执行安排",
        "research": r"研究|论文|试验|结果显示|发现",
        "event": r"会议|论坛|讲座|报名|峰会|年会",
    }
    return {label for label, pattern in signal_patterns.items() if re.search(pattern, sentence, re.IGNORECASE)}


def _signal_weight(label):
    return {
        "policy_release": 3,
        "payment_reform": 5,
        "data_interop": 4,
        "platform_construction": 4,
        "standard_interface": 5,
        "execution_path": 4,
        "impact_execution": 5,
        "research": 4,
        "event": 1,
    }.get(label, 1)


def summarize_article(row):
    cleaned_text = re.sub(r"\s+", " ", (row.get("cleaned_text") or "")).strip()
    if cleaned_text:
        sentences = [segment.strip() for segment in re.split(r"(?<=[。！？!?])\s*", cleaned_text) if segment.strip()]
        sentences = [sentence for sentence in sentences if not any(re.search(pattern, sentence, re.IGNORECASE) for pattern in SUMMARY_NOISE_PATTERNS)]
        if sentences:
            ranked_sentences = sorted(
                sentences,
                key=lambda sentence: (_sentence_priority(sentence), len(sentence)),
                reverse=True,
            )
            summary_parts = []
            covered_topics = set()
            covered_signals = set()
            first_sentence = ranked_sentences[0]
            summary_parts.append(first_sentence)
            covered_topics.update(_sentence_topics(first_sentence))
            covered_signals.update(_sentence_signal_labels(first_sentence))

            remaining_sentences = [sentence for sentence in ranked_sentences[1:] if sentence not in summary_parts]
            if remaining_sentences:
                second_sentence = max(
                    remaining_sentences,
                    key=lambda sentence: (
                        _sentence_priority(sentence)
                        + 6 * len(_sentence_topics(sentence) - covered_topics)
                        + 4 * len(_sentence_signal_labels(sentence) - covered_signals)
                        - 3 * len(_sentence_topics(sentence) & covered_topics),
                        len(sentence),
                    ),
                )
                summary_parts.append(second_sentence)
                covered_topics.update(_sentence_topics(second_sentence))
                covered_signals.update(_sentence_signal_labels(second_sentence))

            remaining_sentences = [sentence for sentence in ranked_sentences if sentence not in summary_parts]
            if remaining_sentences:
                third_sentence = max(
                    remaining_sentences,
                    key=lambda sentence: (
                        sum(_signal_weight(label) for label in (_sentence_signal_labels(sentence) - covered_signals)),
                        len(_sentence_topics(sentence) - covered_topics),
                        _sentence_priority(sentence),
                        len(sentence),
                    ),
                )
                new_signal_count = len(_sentence_signal_labels(third_sentence) - covered_signals)
                if new_signal_count >= 1 and len(" ".join(summary_parts + [third_sentence])) <= 180:
                    summary_parts.append(third_sentence)

            summary = " ".join(summary_parts).strip()
            return summary[:180]
        return cleaned_text[:180]
    digest = (row.get("digest") or "").strip()
    if digest:
        return digest[:180]
    title = (row.get("title") or "未知标题").strip()
    return f"本文围绕《{title}》展开，当前仅有标题元数据可用。"


def explain_why_it_matters(row):
    text = " ".join([
        (row.get("title") or ""),
        (row.get("summary") or ""),
        (row.get("cleaned_text") or ""),
    ])
    category = (row.get("category") or "").strip()

    if category == "政策规范" or any(keyword in text for keyword in ["医保支付", "支付改革", "通知", "办法", "方案", "新规"]):
        if any(keyword in text for keyword in ["数据互通", "平台建设", "标准接口"]):
            return "值得关注：这会影响医院执行口径、医保支付衔接、信息平台改造与后续落地安排。"
        return "值得关注：这会影响医院执行口径、医保支付衔接与后续落地安排。"

    if category == "招标采购信息" or any(keyword in text for keyword in ["招标", "采购", "中标", "项目"]):
        return "值得关注：这反映了近期项目需求、预算投向与潜在招采机会。"

    if category == "会议讲座" or any(keyword in text for keyword in ["会议", "报名", "论坛", "讲座", "峰会", "年会"]):
        return "值得关注：这有助于跟进今年重点议题变化、日程窗口与实际参与机会。"

    if category == "研究论文" or any(keyword in text for keyword in ["研究", "论文", "试验", "结果显示", "发现"]):
        return "值得关注：这提供了可继续验证的证据线索，有助于判断研究价值与后续跟踪方向。"

    if category == "产品发布/企业动态" or any(keyword in text for keyword in ["发布会", "新品", "合作", "布局", "解决方案", "产品"]):
        return "值得关注：这能帮助判断厂商产品方向、合作动向与行业竞争信号。"

    if any(keyword in text for keyword in ["数据互通", "平台建设", "标准接口"]):
        return "值得关注：这关系到信息平台建设、互联互通与后续落地效率。"

    return "值得关注：这条内容可能影响近期行业判断、执行节奏或信息跟进重点。"


def article_priority(item):
    fetch_status = (item.get("fetch_status") or "").strip().lower()
    fetch_score = {
        "normalized": 40,
        "fetched": 20,
        "partial": 10,
        "pending": 0,
    }.get(fetch_status, 0)
    source_score = source_priority(item.get("source_account"))
    text_score = min(len((item.get("cleaned_text") or "").strip()), 300) // 10
    ocr_score = 8 if int(item.get("ocr_applied") or 0) else 0
    ocr_summary_score = min(len((item.get("ocr_summary") or "").strip()), 80) // 20
    published_at = int(item.get("published_at") or 0)
    return (fetch_score + source_score + text_score + ocr_score + ocr_summary_score, published_at)


def summarize_section(section_name, items):
    if not items:
        return ""
    top_titles = "、".join(item.get("title") or "未知标题" for item in items[:2])
    keywords = []
    for item in items[:3]:
        for candidate in [item.get("summary") or "", item.get("cleaned_text") or ""]:
            for keyword in ["医保支付", "支付改革", "数据互通", "平台建设", "标准接口", "报名", "会议", "研究", "招标", "采购"]:
                if keyword in candidate and keyword not in keywords:
                    keywords.append(keyword)
    keyword_text = "、".join(keywords[:3])

    if section_name == "政策规范":
        return f"本栏重点关注{keyword_text or '近期政策动作'}，反映医保政策执行口径与落地重点；重点内容包括：{top_titles}。"
    if section_name == "招标采购信息":
        return f"本栏主要跟踪{keyword_text or '项目采购与招采动向'}，可用于判断近期项目需求与预算方向；重点内容包括：{top_titles}。"
    if section_name == "研究论文":
        return f"本栏集中呈现{keyword_text or '研究进展与证据线索'}，有助于把握近期研究方向与验证重点；重点内容包括：{top_titles}。"
    if section_name == "会议讲座":
        return f"本栏聚焦{keyword_text or '会议议题与报名窗口'}，便于跟进近期活动安排与参与机会；重点内容包括：{top_titles}。"
    if section_name == "产品发布/企业动态":
        return f"本栏关注{keyword_text or '产品布局与企业动向'}，有助于观察厂商策略与市场竞争信号；重点内容包括：{top_titles}。"
    if section_name == "行业观察/评论":
        return f"本栏汇总{keyword_text or '行业观察与趋势判断'}，可用于快速把握近期讨论焦点；重点内容包括：{top_titles}。"
    return f"本栏收录了 {len(items)} 篇内容，重点包括：{top_titles}。"


def build_overview(sections):
    if not sections:
        return ""

    highlights = []
    if "政策规范" in sections:
        policy_items = sections["政策规范"].get("items", [])
        policy_text = " ".join(
            " ".join([item.get("summary") or "", item.get("cleaned_text") or ""]) for item in policy_items[:2]
        )
        policy_keywords = [keyword for keyword in ["医保支付", "支付改革", "数据互通", "标准接口", "平台建设"] if keyword in policy_text]
        if policy_keywords:
            highlights.append(f"政策端重点落在{'、'.join(policy_keywords[:2])}")
        elif policy_items:
            highlights.append("政策端值得关注近期执行口径与落地变化")

    if "会议讲座" in sections:
        meeting_items = sections["会议讲座"].get("items", [])
        meeting_text = " ".join(
            " ".join([item.get("summary") or "", item.get("cleaned_text") or ""]) for item in meeting_items[:2]
        )
        meeting_keywords = [keyword for keyword in ["报名", "议题", "会议", "讲座", "日程"] if keyword in meeting_text]
        if meeting_keywords:
            highlights.append(f"会议端关注{'、'.join(meeting_keywords[:2])}")
        elif meeting_items:
            highlights.append("会议端可留意近期议题与参与窗口")

    if "研究论文" in sections:
        research_items = sections["研究论文"].get("items", [])
        if research_items:
            highlights.append("研究端可继续跟踪近期证据进展与验证方向")

    if "招标采购信息" in sections:
        bid_items = sections["招标采购信息"].get("items", [])
        if bid_items:
            highlights.append("招采端反映出近期项目需求与预算动向")

    if not highlights:
        first_section = next(iter(sections.values()), None)
        first_item = (first_section or {}).get("items", [{}])[0]
        title = first_item.get("title") or "今日重点内容"
        return f"今日总览：建议优先关注《{title}》及相关栏目更新。"

    return f"今日总览：{'，'.join(highlights[:3])}。"


def build_brief_payload(domain_name, brief_date, rows):
    deduped_rows = _dedupe_rows(rows)
    sections = OrderedDict((name, []) for name in SECTION_ORDER)
    for row in deduped_rows:
        category = classify_article_title(row.get("title"))
        sections.setdefault(category, [])
        item = {
            "title": row.get("title") or "未知标题",
            "link": row.get("link") or "",
            "source_account": row.get("nickname") or "",
            "published_at": int(row.get("create_time") or 0),
            "category": category,
            "fetch_status": row.get("fetch_status") or "pending",
            "cleaned_text": row.get("cleaned_text") or "",
            "extraction_profile": row.get("extraction_profile") or "default",
            "extraction_profile_version": row.get("extraction_profile_version") or "",
            "ocr_applied": int(row.get("ocr_applied") or 0),
            "ocr_summary": row.get("ocr_summary") or "",
            "summary": summarize_article(row),
        }
        item["why_it_matters"] = explain_why_it_matters(item)
        sections[category].append(item)

    sections = OrderedDict(
        (name, {
            "section_summary": summarize_section(name, sorted(items, key=article_priority, reverse=True)),
            "items": sorted(items, key=article_priority, reverse=True),
        })
        for name, items in sections.items() if items
    )
    return {
        "domain": domain_name,
        "brief_date": brief_date,
        "total_candidates": len(rows),
        "total_selected": len(deduped_rows),
        "overview": build_overview(sections),
        "sections": sections,
    }


def render_brief_markdown(payload):
    lines = [f"# {payload['domain']} 每日简报", "", f"日期：{payload['brief_date']}", ""]
    lines.append(f"候选 {payload['total_candidates']} 条，去重后保留 {payload['total_selected']} 条")
    lines.append("")
    if payload.get("overview"):
        lines.append(f"> {payload['overview']}")
        lines.append("")
    for section, section_payload in payload.get("sections", {}).items():
        lines.append(f"## {section}")
        lines.append("")
        if section_payload.get("section_summary"):
            lines.append(f"> {section_payload['section_summary']}")
            lines.append("")
        for item in section_payload.get("items", []):
            lines.append(f"- **{item['title']}**")
            lines.append(f"  - 来源：{item['source_account']}")
            lines.append(f"  - 摘要：{item['summary']}")
            lines.append(f"  - 关注点：{item['why_it_matters']}")
            lines.append(f"  - 链接：{item['link']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
