#!/usr/bin/env python3
"""Persist board choice only while installation is unfinished and idle."""
import sys
from apply_commissioning_guard import check_unfinished_idle
from board_profiles import confirm,detect

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Expected board ID')
    check_unfinished_idle()
    confirm(sys.argv[1],detect())
