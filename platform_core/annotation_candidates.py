from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .task_runtime import ArtifactStore


@dataclass(frozen=True)
class CandidateDecision:
    image_id: str
    accepted: bool


@dataclass(frozen=True)
class CandidatePage:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total: int


class CandidateStore:
    def __init__(self, artifacts: ArtifactStore, *, task_id: str, page_size: int = 50):
        if not 1 <= int(page_size) <= 200:
            raise ValueError("page_size must be between 1 and 200")
        self.artifacts = artifacts
        self.task_id = str(task_id)
        self.page_size = int(page_size)

    def initialize(self, *, labels: list[str], total_images: int) -> None:
        self.artifacts.atomic_write_json(self.task_id, "candidates/manifest.json", {
            "schema_version": 1,
            "labels": list(labels),
            "total_images": max(0, int(total_images)),
            "page_size": self.page_size,
            "pages": [],
            "items": 0,
        })

    def append_items(self, items: Iterable[dict[str, Any]]) -> None:
        manifest = self._manifest()
        pending = [self._normalize(item) for item in items]
        page_counts = [int(value) for value in manifest.get("pages") or []]
        if page_counts and page_counts[-1] < self.page_size and pending:
            page_number = len(page_counts) - 1
            reference = self._page_ref(page_number)
            page = list(self.artifacts.read_json(self.task_id, reference, default=[]))
            take = min(self.page_size - len(page), len(pending))
            page.extend(pending[:take])
            pending = pending[take:]
            self.artifacts.atomic_write_json(self.task_id, reference, page)
            page_counts[-1] = len(page)
            manifest["items"] = int(manifest.get("items") or 0) + take
            manifest["pages"] = page_counts
            self.artifacts.atomic_write_json(self.task_id, "candidates/manifest.json", manifest)
        while pending:
            page_number = len(page_counts)
            chunk = pending[: self.page_size]
            pending = pending[self.page_size :]
            self.artifacts.atomic_write_json(self.task_id, self._page_ref(page_number), chunk)
            page_counts.append(len(chunk))
            manifest["pages"] = page_counts
            manifest["items"] = int(manifest.get("items") or 0) + len(chunk)
            self.artifacts.atomic_write_json(self.task_id, "candidates/manifest.json", manifest)

    def read_page(self, *, cursor: str | None, limit: int = 50) -> CandidatePage:
        manifest = self._manifest()
        try:
            offset = max(0, int(cursor or 0))
        except ValueError as error:
            raise ValueError("candidate cursor must be numeric") from error
        bounded = max(1, min(200, int(limit)))
        items = self._read_range(offset, bounded)
        total = int(manifest.get("items") or 0)
        next_offset = offset + len(items)
        return CandidatePage(items, str(next_offset) if next_offset < total else None, total)

    def apply_decisions(self, decisions: Iterable[CandidateDecision]) -> None:
        selected = {str(item.image_id): bool(item.accepted) for item in decisions}
        if not selected:
            return
        manifest = self._manifest()
        for page_number in range(len(manifest.get("pages") or [])):
            reference = self._page_ref(page_number)
            page = list(self.artifacts.read_json(self.task_id, reference, default=[]))
            changed = False
            for item in page:
                image_id = str(item.get("image_id") or "")
                if image_id in selected and item.get("accepted") is not selected[image_id]:
                    item["accepted"] = selected[image_id]
                    changed = True
            if changed:
                self.artifacts.atomic_write_json(self.task_id, reference, page)

    def summary(self) -> dict[str, int]:
        manifest = self._manifest()
        summary = {
            "total": 0, "success": 0, "empty": 0, "failed": 0,
            "accepted": 0, "rejected": 0, "unreviewed": 0, "boxes": 0,
        }
        for item in self._read_range(0, int(manifest.get("items") or 0)):
            summary["total"] += 1
            status = str(item.get("status") or "failed")
            if status in {"success", "empty", "failed"}:
                summary[status] += 1
            if item.get("accepted") is True:
                summary["accepted"] += 1
            elif item.get("accepted") is False:
                summary["rejected"] += 1
            else:
                summary["unreviewed"] += 1
            summary["boxes"] += len(item.get("boxes") or [])
        return summary

    def all_items(self) -> list[dict[str, Any]]:
        manifest = self._manifest()
        return self._read_range(0, int(manifest.get("items") or 0))

    def reject_all_reviewable(self) -> None:
        self.apply_decisions(
            CandidateDecision(image_id=str(item["image_id"]), accepted=False)
            for item in self.all_items()
            if item.get("status") in {"success", "empty"}
        )

    def _manifest(self) -> dict[str, Any]:
        manifest = self.artifacts.read_json(self.task_id, "candidates/manifest.json", default=None)
        if not isinstance(manifest, dict):
            raise FileNotFoundError("annotation candidate manifest does not exist")
        return dict(manifest)

    def _read_range(self, offset: int, limit: int) -> list[dict[str, Any]]:
        manifest = self._manifest()
        result = []
        end = offset + max(0, limit)
        page_start = 0
        for page_number, raw_count in enumerate(manifest.get("pages") or []):
            page_count = int(raw_count)
            page_end = page_start + page_count
            if page_end > offset and page_start < end:
                page = self.artifacts.read_json(self.task_id, self._page_ref(page_number), default=[])
                left = max(0, offset - page_start)
                right = min(len(page), end - page_start)
                result.extend(dict(item) for item in page[left:right])
            page_start = page_end
            if page_start >= end:
                break
        return result

    @staticmethod
    def _page_ref(page_number: int) -> str:
        return f"candidates/page-{page_number:06d}.json"

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        image_id = str(normalized.get("image_id") or "")
        if not image_id:
            raise ValueError("candidate image_id is required")
        normalized["image_id"] = image_id
        normalized["accepted"] = None
        normalized["boxes"] = [dict(box) for box in normalized.get("boxes") or []]
        return normalized
