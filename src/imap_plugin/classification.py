from __future__ import annotations

import re
import unicodedata
from email.utils import getaddresses
from typing import Any, Mapping

from .contracts import Classification, MessageRef


CLASSIFIER_VERSION = "phishing-heuristics-v1"
PRIORITY_VERSION = "priority-rules-v1"

PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all instructions",
    "system message",
    "developer message",
    "call the tool",
    "use the tool",
    "delete this email",
    "send an email",
    "reveal your prompt",
)
URGENCY_PATTERNS = (
    "act now", "urgent", "immediately", "within 24 hours", "account suspended",
    "final warning", "dringend", "onmiddellijk", "vandaag betalen",
)
PAYMENT_PATTERNS = (
    "wire transfer", "bank details", "invoice overdue", "gift card", "crypto payment",
    "iban", "betaling", "factuur", "rekeningnummer",
)
CREDENTIAL_PATTERNS = (
    "verify your account", "confirm your password", "login now", "sign in to avoid",
    "reset your password", "credentials", "wachtwoord", "inloggen",
)


def _addresses(value: str) -> list[str]:
    return [address.casefold() for _, address in getaddresses([value]) if "@" in address]


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip().rstrip(".").casefold()


def _registrable_hint(domain: str) -> str:
    labels = [label for label in domain.split(".") if label]
    return ".".join(labels[-2:]) if len(labels) >= 2 else domain


def _has_unicode_or_punycode(domain: str) -> bool:
    return domain.startswith("xn--") or ".xn--" in domain or any(ord(char) > 127 for char in domain)


def _mixed_scripts(value: str) -> bool:
    scripts: set[str] = set()
    for char in value:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        for script in ("LATIN", "CYRILLIC", "GREEK"):
            if script in name:
                scripts.add(script)
    return len(scripts) > 1


def assess_suspicion(
    message_ref: MessageRef,
    message: Mapping[str, Any],
    signals: Mapping[str, Any],
    account_address: str,
) -> Classification:
    reasons: list[str] = []
    score = 0
    authentication_trusted = signals.get("authentication_trusted") is True
    authentication = str(signals.get("authentication", "")).casefold() if authentication_trusted else ""
    if any(token in authentication for token in ("dmarc=fail", "dkim=fail", "spf=fail")):
        reasons.append("authentication_failure_reported")
        score += 3
    elif authentication and not any(token in authentication for token in ("dmarc=pass", "dkim=pass", "spf=pass")):
        reasons.append("authentication_not_confirmed")
        score += 1
    elif signals.get("authentication_observed") and not authentication_trusted:
        reasons.append("authentication_header_not_from_trusted_server")

    from_addresses = _addresses(str(message.get("from", "")))
    reply_addresses = _addresses(str(signals.get("reply_to", "")))
    from_domain = _domain(from_addresses[0]) if from_addresses else ""
    reply_domain = _domain(reply_addresses[0]) if reply_addresses else ""
    if from_domain and reply_domain and _registrable_hint(from_domain) != _registrable_hint(reply_domain):
        reasons.append("from_reply_to_domain_mismatch")
        score += 2
    if from_domain and (_has_unicode_or_punycode(from_domain) or _mixed_scripts(from_domain)):
        reasons.append("unicode_or_punycode_sender_domain")
        score += 2
    account_domain = _domain(account_address)
    if from_domain and account_domain and from_domain != account_domain:
        left = from_domain.replace("-", "").replace(".", "")
        right = account_domain.replace("-", "").replace(".", "")
        if left != right and (left in right or right in left):
            reasons.append("sender_domain_looks_like_account_domain")
            score += 2

    if int(signals.get("link_mismatch_count", 0) or 0) > 0:
        reasons.append("visible_link_and_destination_mismatch")
        score += 2
    if int(signals.get("remote_url_count", 0) or 0) > 10:
        reasons.append("unusually_many_remote_links")
        score += 1

    text = (str(message.get("subject", "")) + "\n" + str(message.get("text", ""))).casefold()
    if any(pattern in text for pattern in URGENCY_PATTERNS):
        reasons.append("urgent_or_threatening_language")
        score += 1
    if any(pattern in text for pattern in PAYMENT_PATTERNS):
        reasons.append("payment_or_transfer_language")
        score += 1
    if any(pattern in text for pattern in CREDENTIAL_PATTERNS):
        reasons.append("credential_request_language")
        score += 2
    if any(pattern in text for pattern in PROMPT_INJECTION_PATTERNS):
        reasons.append("prompt_injection_language")
        score += 3

    reasons = list(dict.fromkeys(reasons))
    if score >= 5:
        label = "suspicious"
    elif score >= 2:
        label = "needs_review"
    else:
        label = "no_obvious_indicators"
    explanation = (
        "Advisory only. This message has indicators that deserve review: " + ", ".join(reason.replace("_", " ") for reason in reasons) + "."
        if reasons
        else "Advisory only. The local checks found no obvious indicators; this is not a guarantee that the message is safe."
    )
    return Classification(
        message_ref=message_ref,
        label=label,
        reason_codes=tuple(reasons),
        explanation=explanation,
        version=CLASSIFIER_VERSION,
    )


def rank_priority(
    message_ref: MessageRef,
    message: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> Classification:
    text = (str(message.get("subject", "")) + "\n" + str(message.get("text", ""))).casefold()
    sender = str(message.get("from", "")).casefold()
    high_keywords = [str(value).casefold() for value in rules.get("high_keywords", [])][:25]
    low_keywords = [str(value).casefold() for value in rules.get("low_keywords", [])][:25]
    important_senders = [str(value).casefold() for value in rules.get("important_senders", [])][:25]
    reasons: list[str] = []
    score = 0
    if any(value and value in sender for value in important_senders):
        reasons.append("approved_important_sender_rule")
        score += 3
    if any(value and value in text for value in high_keywords):
        reasons.append("approved_high_priority_keyword_rule")
        score += 2
    if any(value and value in text for value in low_keywords):
        reasons.append("approved_low_priority_keyword_rule")
        score -= 2
    if "\\Seen" not in message.get("flags", []):
        reasons.append("unread")
        score += 1
    label = "high" if score >= 2 else ("low" if score <= -2 else "normal")
    explanation = "Local advisory priority based only on the customer-approved rules"
    if reasons:
        explanation += ": " + ", ".join(reason.replace("_", " ") for reason in reasons)
    explanation += ". It does not hide or move mail."
    return Classification(
        message_ref=message_ref,
        label=label,
        reason_codes=tuple(reasons),
        explanation=explanation,
        version=PRIORITY_VERSION,
    )


def cleanup_category(
    message: Mapping[str, Any],
    signals: Mapping[str, Any],
    suspicion_label: str,
) -> dict[str, Any]:
    if suspicion_label in {"suspicious", "needs_review"}:
        return {
            "category": "needs_review",
            "reason": "Suspicious mail is never unsubscribed automatically or through one-click cleanup.",
            "one_click_eligible": False,
            "browser_eligible": False,
            "mailto_available": False,
        }
    urls = list(signals.get("list_unsubscribe_https", []))
    browser_urls = urls + list(signals.get("body_unsubscribe_https", []))
    one_click = bool(signals.get("list_unsubscribe_one_click"))
    dkim_pass = (
        signals.get("authentication_trusted") is True
        and "dkim=pass" in str(signals.get("authentication", "")).casefold()
    )
    if urls and one_click and dkim_pass:
        return {
            "category": "unsubscribe",
            "reason": "RFC 8058 one-click headers and a reported DKIM pass are present; the endpoint still requires safety validation and confirmation.",
            "one_click_eligible": True,
            "browser_eligible": False,
            "mailto_available": bool(signals.get("list_unsubscribe_mailto")),
        }
    if browser_urls and dkim_pass:
        return {
            "category": "unsubscribe",
            "reason": "A signed unsubscribe page is available; opening it in the browser still requires exact list confirmation.",
            "one_click_eligible": False,
            "browser_eligible": True,
            "mailto_available": bool(signals.get("list_unsubscribe_mailto")),
        }
    if signals.get("list_unsubscribe_mailto") and dkim_pass:
        return {
            "category": "needs_review",
            "reason": "Only a mailto unsubscribe option is available; it requires the separate exact draft and send review.",
            "one_click_eligible": False,
            "browser_eligible": False,
            "mailto_available": True,
        }
    if browser_urls or signals.get("list_unsubscribe_mailto"):
        return {
            "category": "needs_review",
            "reason": "Unsubscribe metadata exists but does not meet the guarded one-click requirements.",
            "one_click_eligible": False,
            "browser_eligible": False,
            "mailto_available": bool(signals.get("list_unsubscribe_mailto")),
        }
    return {
        "category": "keep_but_organize",
        "reason": "No guarded one-click unsubscribe metadata was found; confirmed Junk or Bin handling may be safer.",
        "one_click_eligible": False,
        "browser_eligible": False,
        "mailto_available": False,
    }
