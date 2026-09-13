from pathlib import Path

path = Path("platform_core/storage/import_tasks.py")
text = path.read_text(encoding="utf-8")
original = text

old = '''def _sha256_stream(stream) -> str:\n    digest = hashlib.sha256()\n    for chunk in iter(lambda: stream.read(1024 * 1024), b""):\n        digest.update(chunk)\n    return digest.hexdigest()\n'''
new = '''def _sha256_stream(stream, *, cancelled=None) -> str:\n    digest = hashlib.sha256()\n    for chunk in iter(lambda: stream.read(1024 * 1024), b""):\n        if cancelled is not None and cancelled():\n            raise InterruptedError("storage scan cancelled")\n        digest.update(chunk)\n    return digest.hexdigest()\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''    @staticmethod\n    def _inspect(provider, source, item) -> dict[str, Any]:\n        key = str(item.key)\n        base = {\n'''
new = '''    @staticmethod\n    def _inspect(provider, source, item, *, cancelled=None) -> dict[str, Any]:\n        key = str(item.key)\n\n        def ensure_active() -> None:\n            if cancelled is not None and cancelled():\n                raise InterruptedError("storage scan cancelled")\n\n        ensure_active()\n        base = {\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''            with closing(provider.open_reader(key)) as stream:\n                with Image.open(stream) as image:\n                    width, height = image.size\n                    image.verify()\n            content_sha256 = str(item.sha256 or "").strip().lower()\n'''
new = '''            with closing(provider.open_reader(key)) as stream:\n                with Image.open(stream) as image:\n                    width, height = image.size\n                    image.verify()\n            # A remote image read/decode may take seconds. Re-check before any\n            # follow-up reader (for example SHA calculation) so Stop does not\n            # start more remote I/O after cancellation became durable.\n            ensure_active()\n            content_sha256 = str(item.sha256 or "").strip().lower()\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''                with closing(provider.open_reader(key)) as stream:\n                    content_sha256 = _sha256_stream(stream)\n            if int(item.size_bytes or 0) <= 0:\n'''
new = '''                with closing(provider.open_reader(key)) as stream:\n                    content_sha256 = _sha256_stream(stream, cancelled=cancelled)\n            ensure_active()\n            if int(item.size_bytes or 0) <= 0:\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''        except (UnidentifiedImageError, OSError, ValueError) as error:\n            base.update({"status": "INVALID", "error": redact_storage_error(error)})\n'''
new = '''        except InterruptedError:\n            raise\n        except (UnidentifiedImageError, OSError, ValueError) as error:\n            base.update({"status": "INVALID", "error": redact_storage_error(error)})\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''            current_key = str(item.key)\n            batch.append(self._inspect(provider, source, item))\n            if len(batch) >= BATCH_SIZE:\n'''
new = '''            current_key = str(item.key)\n            try:\n                inspected = self._inspect(\n                    provider, source, item, cancelled=context.cancel_requested,\n                )\n            except InterruptedError:\n                # Preserve only work that completed before the cancelled object.\n                # The in-flight object itself must never enter the candidate truth.\n                self._flush_scan_batch(\n                    store, materials, batch, import_format == "yolo",\n                )\n                return TaskStatus.CANCELLED, None\n            if context.cancel_requested():\n                self._flush_scan_batch(\n                    store, materials, batch, import_format == "yolo",\n                )\n                return TaskStatus.CANCELLED, None\n            batch.append(inspected)\n            if len(batch) >= BATCH_SIZE:\n'''
assert old in text
text = text.replace(old, new, 1)

assert text != original
path.write_text(text, encoding="utf-8")
