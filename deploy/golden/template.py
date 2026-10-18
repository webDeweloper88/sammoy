#!/usr/bin/env python3
"""Export application-only golden template. Never reads live .env or data."""
import argparse
import json
import os
from pathlib import Path
import shutil

PROJECT = Path(__file__).resolve().parents[2]
ROOTS = ('apps/kiosk-ui', 'services/io-helper', 'services/wash-engine', 'services/telegram-reports', 'config', 'deploy')
EXCLUDED = {'.git', 'node_modules', 'dist', '__pycache__', '.pytest_cache', 'data', 'secrets', '.venv'}

def ignore(directory, names):
    return [n for n in names if n in EXCLUDED or n.startswith('.env') or n.endswith(('.pyc', '.sqlite3', '.sql', '.log')) or '.bak' in n or n == 'tokenGit']

def export(destination, project=PROJECT):
    destination = Path(destination).resolve()
    project = Path(project).resolve()
    if destination == project or project in destination.parents:
        raise ValueError('Destination must be outside the source project')
    if destination.exists():
        raise ValueError('Destination already exists; refusing overwrite')
    destination.mkdir(mode=0o700, parents=True)
    try:
        for relative in ROOTS:
            source = project / relative
            if source.exists():
                # Reject symlinks instead of following an asset pointing into live data.
                for base, dirs, files in os.walk(source, followlinks=False):
                    blocked = set(ignore(base, dirs + files))
                    dirs[:] = [n for n in dirs if n not in blocked]
                    for name in dirs + [n for n in files if n not in blocked]:
                        if (Path(base) / name).is_symlink():
                            raise ValueError('Source contains a symlink; supply a plain-file template')
                shutil.copytree(source, destination / relative, ignore=ignore)
        shutil.copyfile(project / 'docker-compose.yml', destination / 'docker-compose.yml')
        for name in ('docker-compose.factory.yml', 'docker-compose.relay-only.yml', 'docker-compose.nfc-relay.yml', 'docker-compose.dry-fog.yml'):
            if (project / name).exists():
                shutil.copyfile(project / name, destination / name)
        (destination / 'GOLDEN_TEMPLATE.json').write_text(json.dumps({'format': 1, 'state': 'uncommissioned', 'database_included': False}, indent=2)+'\n')
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    args = parser.parse_args()
    print(export(args.destination))
