# -*- coding: utf-8 -*-
"""Acceptance check for the demo task: a transfer must move a positive quantity.

Immutable and stored outside the target repository and every task workspace. The demo runner
copies it into a workspace copy and runs it in the sandbox; the model never sees or edits it.
Run from the repository root: python3 <this file>. Exit code 0 means the behavior is present.
"""
import os
import shutil
import sys

sys.path.insert(0, os.getcwd())
from db import DB, load_config
from operations import Operations, OperationError

LIVE = os.path.join("data", "openstock.db")
COPY = os.path.join("data", "_accept.db")
failures = []


def check(name, condition):
    print("  [{}] {}".format("OK" if condition else "FAIL", name))
    if not condition:
        failures.append(name)


def stocks(db, code, supplier):
    row = db.cursor().execute(
        "SELECT stock1, stock2 FROM products WHERE item_code=? AND supplier_code=?", (code, supplier)).fetchone()
    return float(row[0]), float(row[1])


def rejected(ops, line, from_stock=1, to_stock=2):
    try:
        ops.transfer(from_stock=from_stock, to_stock=to_stock, lines=[line], operator="ACCEPT")
    except OperationError:
        return True
    return False


def main():
    print("=== ACCEPTANCE: transfers need a positive quantity ===")
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(COPY + ext):
            os.remove(COPY + ext)
    shutil.copy2(LIVE, COPY)
    cfg = load_config()
    cfg["sqlite_path"] = COPY
    db = DB(cfg)
    db.connect()
    ops = Operations(db)
    product = db.cursor().execute(
        "SELECT item_code, supplier_code FROM products WHERE stock1 >= 5 AND supplier_code <> '' LIMIT 1").fetchone()
    code, supplier = product["item_code"], product["supplier_code"]
    line = lambda qty: {"code": code, "supplier_code": supplier, "qty": qty}

    before = stocks(db, code, supplier)
    check("negative quantity is rejected", rejected(ops, line(-3)))
    check("negative quantity leaves stock unchanged", stocks(db, code, supplier) == before)
    check("zero quantity is rejected", rejected(ops, line(0)))
    check("zero quantity leaves stock unchanged", stocks(db, code, supplier) == before)
    documents = db.cursor().execute("SELECT COUNT(*) FROM documents WHERE type='TRANSFER'").fetchone()[0]
    result = ops.transfer(from_stock=1, to_stock=2, lines=[line(2)], operator="ACCEPT")
    after = stocks(db, code, supplier)
    check("a positive transfer still succeeds", bool(result.get("ok")))
    check("positive transfer moves exactly 2 from stock1 to stock2",
          abs(after[0] - (before[0] - 2)) < 1e-6 and abs(after[1] - (before[1] + 2)) < 1e-6)
    check("only the positive transfer created a document",
          db.cursor().execute("SELECT COUNT(*) FROM documents WHERE type='TRANSFER'").fetchone()[0] == documents + 1)
    print("ACCEPTANCE {}".format("FAILED: " + "; ".join(failures) if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
