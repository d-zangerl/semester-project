import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.coding_harness.model import ModelClient, ModelRejectedError, ModelUnavailableError

KEY = "sk-super-secret-test-key"


def completion(content="{}", usage=None):
    body = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return 200, body


class StubGateway:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                gateway.requests.append({"path": self.path, "body": body,
                                         "authorization": self.headers.get("Authorization")})
                status, payload = gateway.responses.pop(0)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *arguments):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ModelClientTests(unittest.TestCase):
    def gateway(self, *responses):
        gateway = StubGateway(*responses)
        self.addCleanup(gateway.close)
        self.waits = []
        return gateway, ModelClient(gateway.url, "test-model", api_key=KEY, sleep=self.waits.append)

    def test_request_uses_the_openai_compatible_contract_and_returns_the_reply(self):
        gateway, client = self.gateway(completion('{"type":"final","response":"ok"}'))

        reply = client.request([{"role": "user", "content": "hi"}])

        self.assertEqual(reply, '{"type":"final","response":"ok"}')
        sent = gateway.requests[0]
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertEqual(sent["authorization"], f"Bearer {KEY}")
        self.assertEqual(sent["body"]["model"], "test-model")
        self.assertEqual(sent["body"]["messages"], [{"role": "user", "content": "hi"}])
        self.assertFalse(sent["body"]["stream"])
        self.assertEqual(sent["body"]["response_format"]["type"], "json_schema")

    def test_the_response_schema_describes_every_tool_and_edit_mode(self):
        gateway, client = self.gateway(completion())

        client.request([])

        schema = gateway.requests[0]["body"]["response_format"]["json_schema"]["schema"]
        branches = {branch["properties"].get("tool", {}).get("const"): branch for branch in schema["oneOf"]}
        self.assertEqual(set(branches["search"]["properties"]["arguments"]["properties"]), {"query", "path"})
        self.assertTrue(any({"function", "function_content"} <= set(mode["properties"])
                            for mode in branches["edit"]["properties"]["arguments"]["oneOf"]))

    def test_no_authorization_header_is_sent_without_a_key(self):
        gateway = StubGateway(completion())
        self.addCleanup(gateway.close)

        ModelClient(gateway.url, "m").request([])

        self.assertIsNone(gateway.requests[0]["authorization"])

    def test_usage_figures_are_returned_with_the_reply(self):
        _, client = self.gateway(completion(usage={"total_tokens": 1234}))

        reply = client.request([])

        self.assertEqual(reply.tokens, 1234)
        self.assertFalse(reply.tokens_estimated)

    def test_missing_usage_is_reported_as_an_estimate(self):
        _, client = self.gateway(completion("x" * 400))

        reply = client.request([{"role": "user", "content": "y" * 400}])

        self.assertGreater(reply.tokens, 0)
        self.assertTrue(reply.tokens_estimated)

    def test_server_errors_and_rate_limits_are_retried_with_increasing_waits(self):
        gateway, client = self.gateway((500, {}), (429, {}), (503, {}), completion("recovered"))

        self.assertEqual(client.request([]), "recovered")
        self.assertEqual(self.waits, [5, 15, 45])
        self.assertEqual(len(gateway.requests), 4)

    def test_an_outage_that_outlasts_the_retries_is_model_unavailable(self):
        gateway, client = self.gateway((500, {}), (500, {}), (500, {}), (500, {}))

        with self.assertRaises(ModelUnavailableError):
            client.request([])
        self.assertEqual(len(gateway.requests), 4)

    def test_a_rejected_key_raises_immediately_without_retrying(self):
        for status in (401, 403):
            with self.subTest(status=status):
                gateway, client = self.gateway((status, {"error": "bad key"}))

                with self.assertRaises(ModelRejectedError):
                    client.request([])
                self.assertEqual(self.waits, [])
                self.assertEqual(len(gateway.requests), 1)

    def test_an_unreachable_endpoint_is_model_unavailable(self):
        waits = []
        client = ModelClient("http://127.0.0.1:9/v1", "m", sleep=waits.append, timeout_seconds=1)

        with self.assertRaises(ModelUnavailableError):
            client.request([])
        self.assertEqual(waits, [5, 15, 45])

    def test_a_service_without_schema_support_gets_the_request_again_without_it(self):
        gateway, client = self.gateway((400, {"error": "response_format unsupported"}), completion("plain"))

        self.assertEqual(client.request([]), "plain")
        self.assertIn("response_format", gateway.requests[0]["body"])
        self.assertNotIn("response_format", gateway.requests[1]["body"])

    def test_the_key_never_appears_in_errors(self):
        for responses in ([(401, {"error": KEY})], [(500, {"error": KEY})] * 4, [(200, {"unexpected": KEY})] * 4):
            with self.subTest(responses=responses[0][0]):
                _, client = self.gateway(*responses)

                with self.assertRaises(ModelUnavailableError) as caught:
                    client.request([])
                self.assertNotIn(KEY, str(caught.exception))
        self.assertNotIn(KEY, repr(client))

    def test_plain_http_is_refused_for_non_local_endpoints(self):
        with self.assertRaises(ValueError):
            ModelClient("http://example.com/v1", "m")
        ModelClient("https://example.com/v1", "m")
        ModelClient("http://localhost:11434/v1", "m")


if __name__ == "__main__":
    unittest.main()
