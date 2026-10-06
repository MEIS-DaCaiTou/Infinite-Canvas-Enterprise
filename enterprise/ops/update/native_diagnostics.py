"""Read-only, bounded offline log collection for the graphical maintenance tool.

Never opens the business DB or includes raw configuration, canvases or media.
The native layer verifies the source/Python closure before invoking this code.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from enterprise.path_safety import PathSafetyError, assert_no_reparse_ancestors
from enterprise.paths import PortableRootInputs, derive_portable_path_roots
from enterprise.release.current_release import read_current_release_result_from_state_root
from enterprise.runtime.logging import redact_text, redact_value, utc_now
from enterprise.runtime.portable import windows_local_app_data_known_folder
from .diagnostics import LOG_NAMES, _public_snapshot, _read_small_json, _tail_lines
from .historical_install import read_catalog

FILE_BUDGET = 32 * 1024
TOTAL_BUDGET = 1024 * 1024
OMIT_KEYS = {'argv', 'args', 'arguments', 'command', 'commands', 'command_args', 'command_arguments',
             'command_line', 'commandline', 'environment', 'env', 'prompt', 'prompt_text',
             'messages', 'body', 'request_body', 'response_body', 'image', 'images', 'image_data', 'content'}


def _safe(value, secrets):
    if isinstance(value, dict):
        value = {str(key): _safe(item, secrets) for key, item in value.items() if str(key).casefold() not in OMIT_KEYS}
    elif isinstance(value, list):
        value = [_safe(item, secrets) for item in value[:100]]
    return redact_value(_public_snapshot(value), secret_values=secrets)


def collect_project_logs(install_root: Path, catalog_path: Path, *, local_app_data_base: Path | None = None):
    assert_no_reparse_ancestors(install_root)
    current = read_current_release_result_from_state_root(install_root / 'state')
    catalog = read_catalog(catalog_path)
    record = catalog.get(current.release.release_id)
    if record is None or record['manifest_sha256'] != current.release.manifest_sha256:
        raise ValueError('NATIVE_UPGRADE_SOURCE_UNSUPPORTED')
    local = local_app_data_base if local_app_data_base is not None else windows_local_app_data_known_folder()
    roots = derive_portable_path_roots(PortableRootInputs(install_root, local), current.release.release_id)
    # Read only the known secret values for redaction, never export this file.
    secret_values = []
    environment_path = roots.CONFIG_ROOT / 'enterprise.env'
    try:
        assert_no_reparse_ancestors(environment_path, allow_missing=True)
        with environment_path.open('rb') as handle:
            environment = handle.read(64 * 1024 + 1)
        if len(environment) <= 64 * 1024:
            for line in environment.decode('utf-8', errors='replace').splitlines():
                key, separator, value = line.partition('=')
                if separator and re.search(r'password|secret|token|key|credential', key, re.I):
                    value = value.strip().strip('\"\'')
                    if len(value) >= 6: secret_values.append(value)
    except OSError:
        pass
    secrets = tuple(sorted(set(secret_values), key=len, reverse=True))
    sources = {}
    candidates = [(f'runtime/{name}' + (f'.{rotation}' if rotation else ''),
                   roots.LOG_ROOT/'runtime'/(name + (f'.{rotation}' if rotation else '')))
                  for name in sorted(LOG_NAMES) for rotation in range(3)]
    jobs_root = roots.STAGING_ROOT/'update-mvp/jobs'
    assert_no_reparse_ancestors(jobs_root, allow_missing=True)
    jobs = []
    if jobs_root.is_dir():
        for index, path in enumerate(jobs_root.iterdir()):
            if index >= 2048: break
            if re.fullmatch(r'[0-9a-f]{32}', path.name):
                assert_no_reparse_ancestors(path)
                if path.is_dir(): jobs.append(path)
        jobs.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    summaries = {}
    for path in jobs[:3]:
        candidates.append((f'update/{path.name}/events.jsonl', path/'events.jsonl'))
        status_path = path/'status.json'
        assert_no_reparse_ancestors(status_path, allow_missing=True)
        status = _read_small_json(status_path)
        if status is not None: summaries[path.name] = _safe(status, secrets)
    for label, path in candidates:
        try:
            assert_no_reparse_ancestors(path, allow_missing=True)
            if not path.is_file(): continue
            lines = _tail_lines(path, limit=200, secret_values=secrets)
            safe_lines, used = [], 0
            truncated = len(lines) >= 200 or path.stat().st_size > FILE_BUDGET
            for line in reversed(lines):
                try:
                    safe = _safe(json.loads(line), secrets)
                    line = json.dumps(safe, ensure_ascii=False, separators=(',', ':'))
                except (ValueError, RecursionError):
                    line = redact_text(line, secret_values=secrets)
                    if re.search(r'command.?line|argv|PYTHONPATH|data:.*;base64,', line, re.I):
                        line = '[OMITTED_COMMAND_ENVIRONMENT_OR_MEDIA]'
                line = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|AIza[A-Za-z0-9_-]{20,})\b', '[REDACTED]', line)
                for root, tag in ((roots.INSTALL_ROOT, '<INSTALL>'), (roots.RUNTIME_ROOT, '<RUNTIME>')):
                    line = line.replace(str(root), tag).replace(str(root).replace('\\','/'), tag)
                count = len(line.encode('utf-8'))
                if used + count > FILE_BUDGET:
                    truncated = True
                    break
                safe_lines.append(line); used += count
            sources[label] = {'lines':list(reversed(safe_lines)), 'truncated':truncated}
        except (OSError, ValueError, PathSafetyError):
            sources[label] = {'status':'unavailable'}
    runtime_path = roots.RUNTIME_ROOT/'runtime-state.json'
    assert_no_reparse_ancestors(runtime_path, allow_missing=True)
    context_path = roots.RUNTIME_ROOT/'launch-context.json'
    assert_no_reparse_ancestors(context_path, allow_missing=True)
    context = _read_small_json(context_path)
    runtime = (_read_small_json(runtime_path) if context is not None and
               context.get('path_roots_identity') == roots.root_identity else None)
    payload = {'schema_version':'enterprise-native-project-logs-v1', 'generated_at':utc_now(),
        'source_release_id':current.release.release_id, 'sources':sources, 'update_jobs':summaries,
        'runtime':_safe(runtime, secrets) if runtime is not None else {'status':'unavailable'},
        'limits':{'lines_per_source':200, 'bytes_per_source':FILE_BUDGET, 'rotated_files_per_source':2,
                  'recent_update_jobs':3, 'maximum_json_bytes':TOTAL_BUDGET},
        'raw_configuration_included':False, 'business_database_included':False, 'media_files_included':False}
    def encoded():
        return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')
    raw = encoded()
    while len(raw) > TOTAL_BUDGET:
        largest = max(sources.values(), key=lambda item:len(json.dumps(item)), default={})
        if not largest.get('lines'):
            raise ValueError('NATIVE_DIAGNOSTICS_LIMIT_EXCEEDED')
        largest['lines'].pop(0); largest['truncated'] = True
        raw = encoded()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('project-diagnostics.json', raw)
    data = output.getvalue()
    return {'result':'diagnostics_collected', 'project_logs_zip_base64':base64.b64encode(data).decode('ascii'),
            'project_logs_sha256':hashlib.sha256(data).hexdigest(), 'source_count':len(sources),
            'truncated':any(row.get('truncated') for row in sources.values())}
