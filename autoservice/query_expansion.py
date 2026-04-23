"""Query expansion for bilingual KB retrieval.

Background (2026-04-23): the cinnox KB is ~99% English (PDF / XLSX rate
cards from OneSyn), but customer messages are routinely Chinese. FTS5
on trigram tokenizer indexes both scripts, but a Chinese query never
matches English content because the content simply doesn't contain the
Chinese characters the query is searching for.

The parallel ``D:/Work/h2os.cloud/autoservice`` project solves the same
class of problem for English-but-colloquial queries (e.g. "uk" →
"United Kingdom") by **appending** the canonical term to the query
before the FTS pass. This module applies the same idea but extends the
mapping to CJK-to-English so Chinese customer messages can hit English
KB content.

Design principles:

1. **Append, don't replace.** The original customer phrasing stays in
   the query so the Chinese demo chunks (like the hand-written
   ``Service Overview``) still match their own Chinese text. The
   English canonical forms are added on top.

2. **Case- and substring-based matching.** No tokenizer, no NLP —
   simple ``in`` checks against a lowercase query. This keeps the
   module dependency-free and idempotent.

3. **Idempotent.** Running ``expand_query`` twice produces a query
   with duplicate canonical terms; FTS5 BM25 tolerates duplicates
   (same OR term repeated collapses to the same match). No need to
   deduplicate.

4. **Narrow scope, explicit coverage.** Mapping tables are
   hand-curated for the cinnox / CINNOX-M800 domain. Adding a new
   tenant or domain should add a new mapping table rather than
   mutating these (which would couple tenants).

The function ``expand_query`` is deliberately side-effect-free and
synchronous so it can be called from both the sync ``kb_search``
(:mod:`autoservice.dream_agent`) and the async ``_build_customer_prompt``
(:mod:`autoservice.triage_dispatch`) without threading juggling.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# CJK country names → English full names (as they appear in CINNOX rate cards)
# ---------------------------------------------------------------------------
#
# Includes both single-char abbreviations ("英", "美") and full names
# ("英国", "美国") because Chinese customers use both. Matched by
# substring, so "英" also triggers from inside "英语" — acceptable: the
# appended "United Kingdom" just becomes a low-ranked OR term and BM25
# still prioritises on-topic chunks. False positives are cheap here
# because they add signal without removing any.
#
# Country set mirrors ``route_query.py::COUNTRY_ALIAS_MAP`` in the
# parallel autoservice repo, plus the CJK-specific entries Chinese
# callers actually use.
_CJK_COUNTRY_MAP: dict[str, str] = {
    # Full forms
    "美国": "United States",
    "英国": "United Kingdom",
    "法国": "France",
    "德国": "Germany",
    "日本": "Japan",
    "韩国": "South Korea",
    "新加坡": "Singapore",
    "香港": "Hong Kong",
    "台湾": "Taiwan",
    "澳大利亚": "Australia",
    "澳洲": "Australia",
    "加拿大": "Canada",
    "印度": "India",
    "中国": "China",
    "马来西亚": "Malaysia",
    "泰国": "Thailand",
    "菲律宾": "Philippines",
    "印尼": "Indonesia",
    "越南": "Vietnam",
    "阿联酋": "United Arab Emirates",
    # Single-char abbreviations (common in Chinese CSR messages like
    # "英 法 德" for UK/France/Germany).
    "美": "United States",
    "英": "United Kingdom",
    "法": "France",
    "德": "Germany",
    "日": "Japan",
    "韩": "South Korea",
    "新": "Singapore",  # (ambiguous with "新的", but in rate-card context)
    "港": "Hong Kong",
    "台": "Taiwan",
    "澳": "Australia",
}


# ---------------------------------------------------------------------------
# Chinese business / telecom terms → English canonical form
# ---------------------------------------------------------------------------
#
# Each Chinese phrase maps to *space-separated English synonyms* so BM25
# sees multiple match candidates. The English side is intentionally
# redundant ("price pricing cost fee") because different KB chunks use
# different phrasings, and we want OR-level recall.
_CJK_TERM_MAP: dict[str, str] = {
    # Pricing / fees
    "价格": "price pricing cost fee rate",
    "多少钱": "price pricing cost fee",
    "费用": "cost fee charge",
    "收费": "charge fee cost",
    "月租": "monthly rent MRC monthly charge",
    "月费": "monthly fee MRC",
    "报价": "quote quotation pricing",
    "免费": "free included no charge",
    # Plans / subscription
    "套餐": "plan subscription package tier",
    "订阅": "subscription subscribe",
    "包月": "monthly plan subscription",
    "年付": "annual prepayment yearly",
    # Products / features
    "号码": "number DID phone",
    "电话": "phone call voice",
    "短信": "SMS message text",
    "语音": "voice audio",
    "客服": "customer service support",
    "服务": "service offering support",
    "提供": "offer provide provides offered",
    "呼叫中心": "contact center call center",
    "联络中心": "contact center",
    "全渠道": "omnichannel multi-channel",
    "功能": "feature capability function",
    "集成": "integration integrate API",
    "对接": "integration integrate connect",
    "接入": "integrate onboard connect",
    # Operations
    "开通": "provisioning activation activate setup",
    "申请": "request apply provisioning",
    "故障": "fault outage issue failure",
    "工单": "ticket support",
    "升级": "upgrade escalation escalate",
    "紧急": "urgent P1 critical priority",
    "投诉": "complaint escalation",
    "退款": "refund",
    "流程": "process procedure workflow",
    "步骤": "steps procedure",
    "文档": "documentation doc manual",
    "教程": "tutorial guide",
}


# ---------------------------------------------------------------------------
# Telecom acronym → canonical long form
# ---------------------------------------------------------------------------
#
# Borrowed + trimmed from the parallel autoservice repo's
# ``synonym-map.json``. Kept tight to entries that actually show up in
# cinnox KB content; adding more is cheap but noise matters — over-wide
# maps dilute ranking.
_ACRONYM_MAP: dict[str, str] = {
    "did": "DID Direct Inward Dialing",
    "ivr": "IVR Interactive Voice Response",
    "pstn": "PSTN Public Switched Telephone Network",
    "idd": "IDD International Direct Dial",
    "vn": "VN Virtual Number",
    "sso": "SSO Single Sign-On",
    "ad": "AD Active Directory",
    "adfs": "ADFS Active Directory Federation Services",
    "tts": "TTS Text-to-speech",
    "stt": "STT Speech-to-Text",
    "dtmf": "DTMF Dual-Tone Multi-Frequency",
    "mrc": "MRC Monthly Recurring Charge",
    "cli": "CLI Caller ID",
    "asr": "Answer Seizure Ratio",
    "acd": "Average Call Duration",
    "frt": "First Response Time",
    "bsp": "WhatsApp Business Solution Provider",
    "crm": "CRM Customer Relationship Management",
    "sip": "SIP Session Initiation Protocol",
}


# ---------------------------------------------------------------------------
# English country aliases (kept short — mirror parallel repo's COUNTRY_ALIAS_MAP)
# ---------------------------------------------------------------------------
#
# Catches the English shorthand customers type when CJK expansion
# doesn't fire (e.g. English-speaking user saying "uk pricing"). Full
# names are canonical per CINNOX xlsx rate cards.
_EN_COUNTRY_ALIAS_MAP: dict[str, str] = {
    "us": "United States",
    "usa": "United States",
    "uk": "United Kingdom",
    "hk": "Hong Kong",
    "sg": "Singapore",
    "jp": "Japan",
    "au": "Australia",
    "de": "Germany",
    "fr": "France",
    "ca": "Canada",
    "cn": "China",
    "tw": "Taiwan",
    "kr": "South Korea",
    "my": "Malaysia",
    "th": "Thailand",
    "ph": "Philippines",
    "id": "Indonesia",
    "vn": "Vietnam",  # overlaps with "VN" acronym intentionally
    "ae": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "america": "United States",
    "britain": "United Kingdom",
    "england": "United Kingdom",
    "deutschland": "Germany",
}


def expand_query(query: str) -> str:
    """Append English canonical terms to a mixed-language ``query``.

    Returns the original query followed by the set of unique canonical
    English terms it matched (across CJK country names, Chinese business
    terms, telecom acronyms, and English country aliases). The original
    phrasing is always preserved so Chinese-to-Chinese FTS hits still
    rank naturally; the expansion just adds English OR candidates so
    chunks in the English rate-card data become reachable.

    Example::

        expand_query("英国的价格")
          → "英国的价格 United Kingdom price pricing cost fee rate"

        expand_query("DID 怎么开通")
          → "DID 怎么开通 DID Direct Inward Dialing provisioning activation activate setup"

        expand_query("United Kingdom rates")
          → "United Kingdom rates"   (already English; no-op expansion)

    Empty / whitespace-only input returns an empty string so downstream
    FTS tokenizers can short-circuit cleanly.
    """
    if not query or not query.strip():
        return query or ""

    q_lower = query.lower()
    additions: list[str] = []
    seen: set[str] = set()

    def _add(canonical: str) -> None:
        """Append unique canonical terms (split on whitespace so each
        English word becomes its own OR candidate for BM25). Preserves
        insertion order so the log line is deterministic."""
        for token in canonical.split():
            if token not in seen:
                seen.add(token)
                additions.append(token)

    # CJK substring matching — iterate in longest-first order so "英国"
    # wins over bare "英". Otherwise "英国" would add "United Kingdom"
    # twice (once per pass).
    for zh, en in sorted(_CJK_COUNTRY_MAP.items(), key=lambda kv: -len(kv[0])):
        if zh in query:
            _add(en)

    for zh, en in sorted(_CJK_TERM_MAP.items(), key=lambda kv: -len(kv[0])):
        if zh in query:
            _add(en)

    # English acronym / country alias matching uses word-boundary so
    # "did" inside "candidate" doesn't falsely expand. Lowercase-compare
    # against the lowered query.
    for alias, en in sorted(_ACRONYM_MAP.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(alias)}\b", q_lower):
            _add(en)

    for alias, en in sorted(_EN_COUNTRY_ALIAS_MAP.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(alias)}\b", q_lower):
            _add(en)

    if not additions:
        return query
    return query + " " + " ".join(additions)
