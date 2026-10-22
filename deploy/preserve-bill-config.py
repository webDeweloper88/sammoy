#!/usr/bin/env python3
"""Preserve wired cash input when installer changes only service/relay profile."""
import json
from pathlib import Path
import sys
import yaml


def merge(target,current):
    if not isinstance(current,dict) or type(current.get('enabled',True)) is not bool:
        raise ValueError('Invalid current bill input configuration')
    if not isinstance(target,dict) or not isinstance(target.get('bill_acceptor'),dict):
        raise ValueError('Target has no bill input configuration')
    return {**target,'bill_acceptor':{**target['bill_acceptor'],**current,'enabled':current.get('enabled',True)}}

if __name__=='__main__':
    path=Path(sys.argv[1]);current=json.loads(sys.argv[2])
    result=merge(yaml.safe_load(path.read_text()),current)
    path.write_text(yaml.safe_dump(result,sort_keys=False))
