# Owner VIP registry read fix — 2026-10-17

Owner VIP profiles and card lists returned `Wallet peer unavailable` while both wallet nodes were online and synchronized (66 committed operations, zero pending). The signed registry-read RPC failed with PostgreSQL SyntaxError: the date expression used the unqualified alias `day` without AS. Replaced it with explicit `AS usage_day` and retained the Asia/Tashkent date calculation.

Added a real PostgreSQL regression test for empty/populated registry, shared profiles, daily usage, active post, zero monetary balance for VIP, and unchanged journal/state digests after reading. Disposable PostgreSQL suite: 148 tests, OK, one skipped. Production databases are not used by the test runner.
