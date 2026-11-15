"""Pembangunan query Gmail dari filter terstruktur."""
from __future__ import annotations


def build_gmail_query(
    *,
    unread_only: bool,
    newer_than_days: int,
    in_inbox: bool,
    sender_domain: str,
) -> str:
    terms = []
    if unread_only:
        terms.append("is:unread")
    terms.append(f"newer_than:{newer_than_days}d")
    if in_inbox:
        terms.append("in:inbox")
    if sender_domain:
        terms.append(f"from:@{sender_domain}")
    return " ".join(terms)
