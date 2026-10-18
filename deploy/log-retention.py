#!/usr/bin/python3
"""Daily bounded technical-log cleanup. Does not access financial tables or volumes."""
import calendar
from datetime import datetime
import math
import subprocess

def previous_month(now):
    year,month=(now.year-1,12) if now.month==1 else (now.year,now.month-1)
    return now.replace(year=year,month=month,day=min(now.day,calendar.monthrange(year,month)[1]))

def main():
    now=datetime.now().astimezone()
    age=math.ceil((now-previous_month(now)).total_seconds())
    subprocess.run(['journalctl','--rotate'],check=True)
    subprocess.run(['journalctl',f'--vacuum-time={age}s','--vacuum-size=256M'],check=True)
    # Only unused build cache older than the same calendar month; no images,
    # containers, database volumes, uploads, or financial backups are removed.
    subprocess.run(['docker','builder','prune','--force','--filter',f'until={age}s'],check=True)

if __name__=='__main__':main()
