# -*- coding: utf-8 -*-
"""Acceptance check for the demo task: a quote line needs a positive quantity.

Immutable and stored outside the target repository and every task workspace. The demo runner
copies it into a workspace copy and runs it in the sandbox; the model never sees or edits it.
Run from the repository root: python3 <this file>. Exit code 0 means the behavior is present.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
import quotes

failures = []


def check(name, condition):
    print("  [{}] {}".format("OK" if condition else "FAIL", name))
    if not condition:
        failures.append(name)


def create(qty):
    return quotes.create_quote(
        customer_id=1, customer_name="Acceptance", vat_rate=0.2,
        lines=[{"code": "A1", "group_code": "G", "qty": qty, "price": 10}])


def rejected(qty):
    try:
        create(qty)
    except ValueError:
        return True
    return False


def main():
    print("=== ACCEPTANCE: quote lines need a positive quantity ===")
    quotes._STORE = os.path.join(tempfile.mkdtemp(), "quotes.json")
    check("negative quantity is rejected with ValueError", rejected(-2))
    check("zero quantity is rejected with ValueError", rejected(0))
    check("rejected quotes were not stored", quotes._load()["counter"] == 0)
    quote = create(3)
    check("a positive quantity still creates a quote", quote["no"].endswith("-0001"))
    check("the positive quote has the right net amount", abs(quote["net_amount"] - 30.0) < 1e-6)
    print("ACCEPTANCE {}".format("FAILED: " + "; ".join(failures) if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
