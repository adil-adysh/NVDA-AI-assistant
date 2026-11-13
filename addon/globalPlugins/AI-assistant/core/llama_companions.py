"""Pure, explicit companion descriptors; resolving assets belongs to the worker."""
from pathlib import PurePosixPath, Path
import re

from .translation import _
from .llama_model_source import is_standalone_gguf

ROLES = frozenset({'vision', 'draft', 'mtp'})


def companion_identity(path):
    stat = Path(path).stat()
    return f'{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}'


def can_reuse_companion(entry):
    path, identity = entry.get('local_path'), entry.get('file_identity')
    if not path or not identity:
        return False
    if entry.get('kind') == 'hugging_face' and not re.fullmatch(r'[a-fA-F0-9]{40,64}', entry.get('resolved_revision', '')):
        return False
    try:
        return Path(path).is_file() and companion_identity(path) == identity
    except OSError:
        return False


def eligible_artifact(artifact, role='primary'):
    if role not in ROLES | {'primary'}:
        raise ValueError(_('Unknown llama.cpp companion role.'))
    name = str(artifact).replace('\\', '/').rsplit('/', 1)[-1].lower()
    if role != 'vision':
        return is_standalone_gguf(name)
    return name.endswith('.gguf') and not re.search(r'-\d{5}-of-\d{5}\.gguf$', name)


def validate_companions(entries):
    if entries is None:
        return ()
    if not isinstance(entries, (list, tuple)):
        raise ValueError(_('Model companions must be a list.'))
    result, roles = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(_('Invalid model companion.'))
        value = dict(entry)
        role, kind = value.get('role'), value.get('kind')
        if role not in ROLES or role in roles or (role in {'draft', 'mtp'} and roles & {'draft', 'mtp'}):
            raise ValueError(_('Choose one vision projector and one draft or MTP companion.'))
        if kind not in {'local_file', 'hugging_face'}:
            raise ValueError(_('Unsupported companion source kind.'))
        source = value.get('source')
        if not isinstance(source, str) or not source.strip():
            raise ValueError(_('A companion source is required.'))
        for key in ('source', 'artifact', 'revision', 'local_path'):
            text = value.get(key)
            if text is not None and (not isinstance(text, str) or any(ord(char) < 32 for char in text)):
                raise ValueError(_('Companion values must be single-line strings.'))
        value['revision'] = value.get('revision') or 'main'
        value['ownership'] = value.get('ownership') or 'user'
        if value['ownership'] not in {'user', 'addon'}:
            raise ValueError(_('Invalid companion file ownership.'))
        artifact = value.get('artifact')
        if kind == 'hugging_face':
            if not re.fullmatch(r'[\w.-]+/[\w.-]+', source) or not artifact or '\\' in artifact or PurePosixPath(artifact).is_absolute() or '..' in PurePosixPath(artifact).parts:
                raise ValueError(_('Choose an explicit companion file from a Hugging Face repository.'))
            target = artifact
        else:
            target = value.get('local_path') or source
            value['local_path'] = target
        if not eligible_artifact(target, role):
            raise ValueError(_('Choose one GGUF companion file. Multipart GGUF shards are unsupported.'))
        if value.get('local_path') and not eligible_artifact(value['local_path'], role):
            raise ValueError(_('Invalid local companion file.'))
        roles.add(role)
        result.append(value)
    return tuple(result)


def companion_options(entries):
    options = {}
    for entry in validate_companions(entries):
        path = entry.get('local_path')
        if not path:
            continue
        if entry['role'] == 'vision':
            options['mmproj'] = path
        else:
            options['spec-draft-model'] = path
            options['spec-type'] = 'draft-mtp' if entry['role'] == 'mtp' else 'draft-simple'
    return options
