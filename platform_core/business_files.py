"""Resolve public bytes from business records, never from directory membership.

HTTP authentication/project access belongs to the caller. ``records`` may project
existing Task/ModelArtifact records; it must not enumerate files as registrations.
No repository is created or migrated by this read-only resolver.
"""
from dataclasses import dataclass
import hashlib
import json
import mimetypes
from pathlib import Path
from urllib.parse import quote


class BusinessFileNotFound(Exception):
    def __init__(self):
        super().__init__('File not found')


@dataclass(frozen=True)
class BusinessFile:
    path: Path
    filename: str
    media_type: str
    material: object = None
    manager: object = None


_IMAGES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
_MODELS = {'.pt', '.onnx', '.rknn', '.engine', '.bmodel', '.om', '.pdparams', '.pdmodel', '.pdiparams'}
_ALLOWED = {'images': _IMAGES, 'models': _MODELS, 'predictions': _IMAGES,
            'exports': {'.zip'}, 'jobs': _IMAGES | _MODELS,
            'runs': _IMAGES | _MODELS, 'deployment': _MODELS | {'.zip', '.json', '.yml', '.yaml'}}


def _parts(value):
    if not isinstance(value, str) or not value or len(value) > 1500:
        raise BusinessFileNotFound()
    if any(c in value for c in ('\\', ':', '%', '\x00', '?', '#')):
        raise BusinessFileNotFound()
    parts = value.split('/')
    if any(not p or p in {'.', '..'} or p.startswith('.') or p.endswith((' ', '.'))
           or any(ord(c) < 32 for c in p) for p in parts):
        raise BusinessFileNotFound()
    return parts


def _plain(path, boundary):
    """Inspect lexical ancestors before resolve can conceal Windows junctions."""
    path, boundary = Path(path).absolute(), Path(boundary).absolute()
    path.relative_to(boundary)
    current = path
    while True:
        info = current.lstat()
        if current.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise BusinessFileNotFound()
        if current == boundary:
            break
        current = current.parent
    resolved = path.resolve()
    resolved.relative_to(boundary.resolve())
    return resolved


def _read(path, boundary):
    path = _plain(path, boundary)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise BusinessFileNotFound()
    return json.loads(path.read_text(encoding='utf-8'))


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class BusinessFileService:
    def __init__(self, data_dir, *, records=None, material_lookup=None, storage_manager=None):
        self.data_dir = Path(data_dir).absolute()
        self.records = records
        self.material_lookup = material_lookup
        self.storage_manager = storage_manager

    @staticmethod
    def url(project_id, kind, identifier):
        if len(_parts(project_id)) != 1 or kind not in _ALLOWED:
            raise BusinessFileNotFound()
        return '/api/projects/{}/files/{}/{}'.format(
            quote(project_id, safe=''), kind, '/'.join(quote(p, safe='') for p in _parts(identifier)))

    def resolve(self, project_id, kind, identifier):
        return self.resolve_legacy(project_id, kind + '/' + identifier)

    def _existing_records(self, project_id, root, kind, identifier):
        if self.records:
            for row in self.records(project_id, kind) or ():
                if isinstance(row, dict) and str(row.get('project_id') or '') == project_id:
                    yield row
            return  # An injected authoritative owner replaces legacy JSON mirrors.
        if kind in {'models', 'jobs'}:
            algorithms = root / 'algorithms.json'
            if algorithms.is_file():
                rows = _read(algorithms, self.data_dir)
                if isinstance(rows, list):
                    for algorithm in rows:
                        for version in algorithm.get('versions', []):
                            if version.get('stored_path'):
                                yield {'path': version['stored_path']}
            jobs = root / 'jobs'
            if jobs.is_dir():
                _plain(jobs, self.data_dir)
                for metadata in jobs.glob('*/job.json'):
                    job = _read(metadata, self.data_dir)
                    if job.get('project_id', project_id) != project_id:
                        continue
                    for path in job.get('models') or []:
                        if isinstance(path, str):
                            yield {'path': path}
                    for output in job.get('outputs') or []:
                        if isinstance(output, dict) and output.get('path'):
                            yield output
        elif kind == 'predictions' and '/' not in identifier:
            stem = Path(identifier).stem
            prediction_id = stem.rsplit('_', 1)[0]
            if stem.endswith('_input'):
                metadata = root / 'predictions' / (prediction_id + '.evidence.json')
                if metadata.is_file():
                    evidence = _read(metadata, self.data_dir)
                    if (evidence.get('prediction_id') == prediction_id
                            and evidence.get('input_file') == identifier
                            and len(str(evidence.get('input_sha256') or '')) == 64):
                        yield {'path': str(root / 'predictions' / identifier), 'sha256': evidence['input_sha256']}
        elif kind == 'exports' and '/' not in identifier:
            package = Path(identifier).stem
            metadata = root / 'exports' / package / 'model_meta.json'
            if metadata.is_file():
                row = _read(metadata, self.data_dir)
                export_id = str(row.get('export_id') or '')
                if (row.get('project_id') == project_id and export_id
                        and package.endswith('_' + export_id)
                        and row.get('model_path_source') and row.get('model_file')):
                    yield {'path': str(root / 'exports' / identifier)}

    def resolve_legacy(self, project_id, relativepath):
        try:
            if len(_parts(project_id)) != 1:
                raise BusinessFileNotFound()
            parts = _parts(relativepath)
            if len(parts) < 2 or parts[0] not in _ALLOWED:
                raise BusinessFileNotFound()
            kind, identifier = parts[0], '/'.join(parts[1:])
            if Path(identifier).suffix.lower() not in _ALLOWED[kind]:
                raise BusinessFileNotFound()
            root = self.data_dir / 'projects' / project_id
            _plain(root, self.data_dir)
            if kind == 'images' and self.material_lookup and self.storage_manager:
                row = self.material_lookup(project_id, identifier)
                if not row or row.get('stored_name') != identifier:
                    raise BusinessFileNotFound()
                manager = self.storage_manager(project_id)
                path = Path(manager.materialize(row).path)
                return BusinessFile(path, path.name, mimetypes.guess_type(path.name)[0] or 'application/octet-stream', row, manager)
            requested = (root / relativepath).absolute()
            for row in self._existing_records(project_id, root, kind, identifier):
                raw = str(row.get('path') or row.get('source_path') or '')
                if not raw:
                    continue
                recorded = Path(raw)
                if not recorded.is_absolute():
                    recorded = root / recorded
                recorded = recorded.absolute()
                alias = row.get('identifier')
                if alias is not None and alias != identifier:
                    continue
                if recorded != requested and alias is None:
                    continue
                # A cross-root alias is accepted only for a precise, hashed
                # Task/Artifact projection injected by the business owner.
                candidate = _plain(recorded, self.data_dir)
                external = not candidate.is_relative_to(root.resolve())
                if external and (alias != identifier or not row.get('sha256')
                        or not candidate.is_relative_to((self.data_dir / 'task_runtime' / 'artifacts').resolve())):
                    continue
                if not candidate.is_file() or candidate.suffix.lower() not in _ALLOWED[kind]:
                    continue
                digest = str(row.get('sha256') or '').lower()
                if digest and (len(digest) != 64 or _sha(candidate) != digest):
                    raise BusinessFileNotFound()
                return BusinessFile(candidate, candidate.name,
                    mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream')
            raise BusinessFileNotFound()
        except BusinessFileNotFound:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise BusinessFileNotFound() from None
