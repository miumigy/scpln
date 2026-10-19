#!/usr/bin/env python3
import sys

import pytest


def main():
    # pytest を実行し、JUnit XMLレポートを生成する
    # レポートは test-results/results.xml に保存される
    retcode = pytest.main(
        ["--junitxml=test-results/results.xml", "-v", "-s", "-n=0", "tests/"]
    )

    # pytest の終了コードをそのまま返す
    sys.exit(retcode)


if __name__ == "__main__":
    main()
