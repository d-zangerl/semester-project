# -*- coding: utf-8 -*-
"""Protected acceptance check for quote expiry. Kept outside the agent's writable area, mounted read-only,
and run from the root of the code under test. Exit code 0 means every behaviour is present."""
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
os.environ["OPENSTOCK_DB"] = "data/openstock.db"

import quotes

feature_failures, regression_failures = [], []
LINES = [{"code": "A1", "group_code": "G", "qty": 1, "price": 10}]
today = datetime.date.today()
FUTURE = (today + datetime.timedelta(days=30)).isoformat()
PAST = (today - datetime.timedelta(days=1)).isoformat()


def check(failures, name, condition):
    print("  [{}] {}".format("OK" if condition else "FAIL", name))
    if not condition:
        failures.append(name)


def feature(name, condition):
    check(feature_failures, name, condition)


def regression(name, condition):
    check(regression_failures, name, condition)


def create(**options):
    return quotes.create_quote(customer_id=1, customer_name="Acceptance", vat_rate=0.2, lines=LINES, **options)


def rejects(value):
    before = len(quotes.get_quotes())
    try:
        create(valid_until=value)
    except ValueError as error:
        return bool(str(error).strip()) and len(quotes.get_quotes()) == before
    return False


def store_expired_quote():
    """A quote that was valid when created and has since expired."""
    quote = create(valid_until=FUTURE)
    with open(quotes._STORE, encoding="utf-8") as handle:
        data = json.load(handle)
    for stored in data["quotes"]:
        if stored["no"] == quote["no"]:
            stored["valid_until"] = PAST
    with open(quotes._STORE, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return quote["no"]


def client_and_headers():
    import app as openstock
    from auth import SessionManager

    class AcceptanceAuth:
        @staticmethod
        def authenticate(_username, _password):
            return {"id": "acceptance", "name": "Acceptance", "job_title": "Sales", "permissions": "quotes"}

    openstock.SES = SessionManager(AcceptanceAuth())
    session = openstock.SES.login("acceptance", "acceptance")
    return openstock.app.test_client(), {"X-Session-Id": session["session_id"]}


def main():
    with tempfile.TemporaryDirectory(prefix=".quote-acceptance-", dir=os.getcwd()) as directory:
        quotes._STORE = os.path.join(directory, "quotes.json")

        print("=== REGRESSION: quotes without an expiry and existing callers ===")
        plain = create()
        regression("a quote without an expiry is created", plain["valid_until"] == "")
        regression("a quote without an expiry can be read back", quotes.get_quote(plain["no"])["no"] == plain["no"])
        client, headers = client_and_headers()
        listed = client.get("/api/quotes", headers=headers)
        regression("GET /api/quotes still lists quotes",
                   listed.status_code == 200 and any(q["no"] == plain["no"] for q in listed.get_json()["quotes"]))
        posted = client.post("/api/quote", json={"customer_id": 1, "customer_name": "A", "lines": LINES},
                             headers=headers)
        regression("POST without an expiry still succeeds", posted.status_code == 200 and posted.get_json()["ok"] is True)
        regression("deleting a quote still works",
                   client.delete("/api/quote/" + plain["no"], headers=headers).status_code == 200
                   and quotes.get_quote(plain["no"]) is None)

        print("=== FEATURE: quote expiry ===")
        valid = create(valid_until=FUTURE)
        feature("a future ISO date is accepted", valid["valid_until"] == FUTURE)
        today_quote = create(valid_until=today.isoformat())
        feature("a quote valid until today is accepted and not expired",
                quotes.get_quote(today_quote["no"]).get("expired") is False)
        feature("a past date is rejected with a clear error and nothing is stored", rejects(PAST))
        feature("an invalid date is rejected with a clear error and nothing is stored", rejects("31/12/2030"))
        feature("an impossible date is rejected", rejects("2030-02-31"))

        expired_no = store_expired_quote()
        by_no = {q["no"]: q for q in quotes.get_quotes()}
        feature("get_quotes marks an expired quote", by_no[expired_no].get("expired") is True)
        feature("get_quotes does not mark a future quote", by_no[valid["no"]].get("expired") is False)
        feature("get_quote marks an expired quote", quotes.get_quote(expired_no).get("expired") is True)

        no_expiry = create()
        feature("a quote without an expiry is not expired", quotes.get_quote(no_expiry["no"]).get("expired") is False)

        bad = client.post("/api/quote", json={"customer_id": 1, "customer_name": "A", "lines": LINES,
                                                     "valid_until": "not-a-date"}, headers=headers)
        feature("POST with an invalid date returns 400 and ok=false",
                bad.status_code == 400 and bad.get_json()["ok"] is False)
        everything = {q["no"] for q in client.get("/api/quotes", headers=headers).get_json()["quotes"]}
        feature("GET /api/quotes still includes expired quotes", expired_no in everything)
        active = client.get("/api/quotes?active=1", headers=headers)
        active_numbers = {q["no"] for q in active.get_json()["quotes"]}
        feature("GET /api/quotes?active=1 leaves out expired quotes", active.status_code == 200 and expired_no not in active_numbers)
        feature("GET /api/quotes?active=1 keeps active and no-expiry quotes",
                {valid["no"], no_expiry["no"]} <= active_numbers)

    print("REGRESSION {}".format("FAILED: " + "; ".join(regression_failures) if regression_failures else "PASSED"))
    print("FEATURE {}".format("FAILED: " + "; ".join(feature_failures) if feature_failures else "PASSED"))
    return 1 if feature_failures or regression_failures else 0


if __name__ == "__main__":
    sys.exit(main())
