"""Explicit HF metadata and lazy companion downloads, entirely worker-owned."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import tempfile
import urllib.parse
import urllib.request

try:
    from ...core.llama_companions import validate_companions, eligible_artifact, companion_identity, can_reuse_companion
    from ...core.job.execution import check_job_cancelled
    from ...core.translation import _
except ImportError:
    from core.llama_companions import validate_companions, eligible_artifact, companion_identity, can_reuse_companion
    from core.job.execution import check_job_cancelled
    from core.translation import _


def _request(url):
    headers = {'User-Agent': 'NVDA-AI-assistant'}
    token = os.getenv('HF_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return urllib.request.Request(url, headers=headers)


def _safe_artifact(value):
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and '..' not in path.parts and '\\' not in value and ':' not in value


def resolve_hf(repo, revision='main', role='primary'):
    if not isinstance(repo, str) or not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
        raise ValueError(_('Enter a Hugging Face repository as owner/name.'))
    if not isinstance(revision, str) or not revision or any(ord(char) < 32 for char in revision):
        raise ValueError(_('A valid Hugging Face revision is required.'))
    eligible_artifact('probe.gguf', role)
    check_job_cancelled()
    url = f'https://huggingface.co/api/models/{repo}/revision/{urllib.parse.quote(revision, safe="")}?blobs=true'
    with urllib.request.urlopen(_request(url), timeout=10) as response:
        payload = json.load(response)
    check_job_cancelled()
    files = []
    for item in payload.get('siblings', []):
        check_job_cancelled()
        artifact = item.get('rfilename', '')
        if not isinstance(artifact, str) or not artifact.lower().endswith('.gguf') or not _safe_artifact(artifact):
            continue
        lfs = item.get('lfs') or {}
        size = item.get('size', lfs.get('size'))
        size = size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None
        files.append({'artifact': artifact, 'size_bytes': size, 'eligible': eligible_artifact(artifact, role), 'sha256': lfs.get('sha256')})
    return {'repo': repo, 'repository': repo, 'revision': revision, 'commit': payload.get('sha'), 'role': role, 'files': files}


def verify_gguf(path, role):
    path = Path(path)
    if not eligible_artifact(str(path), role):
        raise ValueError(_('Choose one GGUF file. Multipart GGUF shards are unsupported.'))
    check_job_cancelled()
    with path.open('rb') as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:4] != b'GGUF' or struct.unpack('<I', header[4:8])[0] not in {2, 3}:
        raise ValueError(_('The companion file has an invalid or incomplete GGUF header.'))
    return path.resolve()


def _hub_root():
    home = Path(os.getenv('HF_HOME') or (Path(os.getenv('XDG_CACHE_HOME') or Path.home()/'.cache')/'huggingface'))
    return Path(os.getenv('HF_HUB_CACHE') or os.getenv('HUGGINGFACE_HUB_CACHE') or home/'hub').resolve()


def _download(entry, on_stage=None):
    if can_reuse_companion(entry) and Path(entry['local_path']).resolve().is_relative_to(_hub_root()):
        return verify_gguf(entry['local_path'], entry['role']), entry['resolved_revision'], entry.get('source_size')
    metadata = resolve_hf(entry['source'], entry['revision'], entry['role'])
    artifact = next((item for item in metadata['files'] if item['artifact'] == entry['artifact'] and item['eligible']), None)
    if artifact is None:
        raise ValueError(_('The selected companion file is missing or unsupported in this repository.'))
    commit = metadata['commit']
    if not isinstance(commit, str) or not re.fullmatch(r'[a-fA-F0-9]{40,64}', commit):
        raise ValueError(_('Hugging Face did not return a valid immutable revision.'))
    root = _hub_root()
    target = root / ('models--'+entry['source'].replace('/', '--')) / 'snapshots' / commit / entry['artifact']
    if not target.resolve().is_relative_to(root):
        raise ValueError(_('Companion cache path is outside the Hugging Face cache.'))
    if target.is_file():
        if artifact['size_bytes'] is not None and target.stat().st_size != artifact['size_bytes']:
            raise ValueError(_('The cached companion is incomplete. Remove it using your cache tools and retry.'))
        return verify_gguf(target, entry['role']), commit, artifact['size_bytes']
    target.parent.mkdir(parents=True, exist_ok=True)
    if on_stage:
        on_stage('downloading_companion')
    fd, temporary = tempfile.mkstemp(prefix='.nvda-companion-', suffix='.incomplete', dir=target.parent)
    partial = Path(temporary)
    try:
        url = f'https://huggingface.co/{entry["source"]}/resolve/{commit}/{urllib.parse.quote(entry["artifact"], safe="/")}'
        digest, count = hashlib.sha256(), 0
        with os.fdopen(fd, 'wb') as stream:
            with urllib.request.urlopen(_request(url), timeout=10) as response:
                while True:
                    check_job_cancelled()
                    chunk = response.read(1024*1024)
                    if not chunk:
                        break
                    stream.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
        check_job_cancelled()
        if artifact['size_bytes'] is not None and count != artifact['size_bytes']:
            raise ValueError(_('The companion download is incomplete.'))
        if artifact.get('sha256') and digest.hexdigest() != artifact['sha256']:
            raise ValueError(_('The companion download checksum did not match.'))
        # Validate contents using the original GGUF name before publication.
        with partial.open('rb') as stream:
            header = stream.read(24)
        if len(header) != 24 or header[:4] != b'GGUF' or struct.unpack('<I',header[4:8])[0] not in {2,3}:
            raise ValueError(_('The downloaded companion has an invalid GGUF header.'))
        check_job_cancelled()
        # The llama lane serializes our downloads. Preserve any shared-cache writer.
        if not target.exists():
            partial.rename(target)
        return verify_gguf(target, entry['role']), commit, artifact['size_bytes']
    finally:
        partial.unlink(missing_ok=True)


def resolve_companions(companions, on_stage=None):
    result = []
    if on_stage:
        on_stage('checking_companions')
    for entry in validate_companions(companions):
        check_job_cancelled()
        value = dict(entry)
        if entry['kind'] == 'hugging_face':
            path, commit, size = _download(entry, on_stage=on_stage)
            value.update(local_path=str(path), resolved_revision=commit, ownership='user', provenance='hf_hub', source_size=size)
        else:
            value['local_path'] = str(verify_gguf(entry['local_path'], entry['role']))
            value['source_size'] = Path(value['local_path']).stat().st_size
        value['file_identity'] = companion_identity(value['local_path'])
        value['compatibility'] = 'unverified'
        result.append(value)
    check_job_cancelled()
    return {'companions': result}
