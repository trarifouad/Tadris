"""pytest plugin: once the tests are over, writes the name of every module they loaded to
the file named by TADRIS_IMPORT_TRACE, one per line. packaging/check_imports.py runs the
tests with it, to find the modules the app loads at run time that the bundle lacks."""

import os
import sys


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("TADRIS_IMPORT_TRACE")
    if path:
        with open(path, "w", encoding="utf-8") as file:
            file.write("\n".join(sorted(sys.modules)) + "\n")
