#!/usr/bin/env python3
"""触发未签名开发发版（绕过 WINDOWS_CERTIFICATE）。等价于: python trigger_release.py --unsigned"""

from __future__ import annotations

import sys

from trigger_release import main

if __name__ == "__main__":
    main(["--unsigned", *sys.argv[1:]])
