# -*- coding: utf-8 -*-
"""Acceptance check: deleting a missing quote must report not found.

Kept outside the model-writable workspace and copied into it only for checks.
Run from the target-repository root. Exit code 0 means all behaviors are present.
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


def create_quote():
    return quotes.create_quote(
        customer_id=1,
        customer_name="Acceptance",
        vat_rate=0.2,
        lines=[{"code": "A1", "group_code": "G", "qty": 1, "price": 10}],
    )


def main():
    print("=== ACCEPTANCE: deleting a missing quote reports not found ===")
    with tempfile.TemporaryDirectory(prefix=".quote-delete-acceptance-", dir=os.getcwd()) as directory:
        quotes._STORE = os.path.join(directory, "quotes.json")

        existing = create_quote()
        check(
            "delete_quote reports success and removes an existing quote",
            quotes.delete_quote(existing["no"]) is True and quotes.get_quote(existing["no"]) is None,
        )
        check(
            "delete_quote reports false for a missing quote",
            quotes.delete_quote("QT-NOT-FOUND") is False,
        )

        import app as openstock
        from auth import SessionManager

        class AcceptanceAuth:
            @staticmethod
            def authenticate(_username, _password):
                return {
                    "id": "acceptance",
                    "name": "Acceptance",
                    "job_title": "Sales",
                    "permissions": "quotes",
                }

        openstock.SES = SessionManager(AcceptanceAuth())
        session = openstock.SES.login("acceptance", "acceptance")
        client = openstock.app.test_client()

        existing = create_quote()
        deleted = client.delete(
            "/api/quote/" + existing["no"],
            headers={"X-Session-Id": session["session_id"]},
        )
        check(
            "DELETE API returns 200 and ok=true when it deletes a quote",
            deleted.status_code == 200 and deleted.get_json().get("ok") is True,
        )
        missing = client.delete(
            "/api/quote/QT-NOT-FOUND",
            headers={"X-Session-Id": session["session_id"]},
        )
        check(
            "DELETE API returns 404 and ok=false for a missing quote",
            missing.status_code == 404 and missing.get_json().get("ok") is False,
        )

    print("ACCEPTANCE {}".format("FAILED: " + "; ".join(failures) if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
