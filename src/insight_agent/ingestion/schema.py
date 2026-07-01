from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceItem:
    source: str
    provider: str
    content_type: str
    title: str
    text: str
    url: str
    external_id: str = ""
    author: str | None = None
    community: str | None = None
    created_at: str = ""
    metrics: dict[str, int | float | None] = field(default_factory=dict)
    comments: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_legacy_post(self) -> dict[str, Any]:
        comment_text = "\n".join(
            str(comment.get("text", "")).strip()
            for comment in self.comments[:20]
            if str(comment.get("text", "")).strip()
        )
        excerpt = self.text.strip()
        if comment_text:
            excerpt = f"{excerpt}\n\nTop comments:\n{comment_text}".strip()
        return {
            "id": self.external_id or self.url,
            "title": self.title,
            "excerpt": excerpt[:3000],
            "subreddit": self.community or "unknown",
            "url": self.url,
            "created_utc": self.created_at,
            "score": self.metrics.get("score"),
            "comments": self.metrics.get("comments"),
            "source": f"{self.source}_{self.provider}",
            "comment_items": self.comments,
        }


@dataclass
class ProviderResult:
    items: list[EvidenceItem]
    warnings: list[str] = field(default_factory=list)
    source_mode: str = ""
