"""Protocol tests for the real backends against local stand-in servers (not real Ollama/OpenAI)."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from oracle_arc.models import ModelGateway, OllamaBackend, OpenAICompatBackend, RoutingPolicy
from oracle_arc.types import ChatRequest, DataClass


def serve(handler_fn):
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = handler_fn("GET", self.path, None, self.headers)
            self._r(code, body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, payload, dict(self.headers)))
            code, body = handler_fn("POST", self.path, payload, self.headers)
            self._r(code, body)

        def _r(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


REQ = ChatRequest([{"role": "user", "content": "hi"}], temperature=0.1, max_tokens=50, json_mode=True)


class OllamaProtocolTests(unittest.TestCase):
    def test_chat_request_shape_and_response_parsing(self):
        srv, seen = serve(lambda m, p, b, h: (200, {"message": {"role": "assistant", "content": "hello"},
                                                    "prompt_eval_count": 7, "eval_count": 3}))
        self.addCleanup(srv.server_close); self.addCleanup(srv.shutdown)
        be = OllamaBackend("qwen2.5:7b", f"http://127.0.0.1:{srv.server_address[1]}")
        r = be.chat(REQ)
        path, body, _ = seen[0]
        self.assertEqual(path, "/api/chat")
        self.assertEqual((body["model"], body["stream"], body["format"]), ("qwen2.5:7b", False, "json"))
        self.assertEqual((body["options"]["temperature"], body["options"]["num_predict"]), (0.1, 50))
        self.assertEqual((r.text, r.prompt_tokens, r.completion_tokens, r.backend), ("hello", 7, 3, "ollama"))

    def test_health_checks_model_is_pulled(self):
        srv, _ = serve(lambda m, p, b, h: (200, {"models": [{"name": "qwen2.5:7b"}]}))
        self.addCleanup(srv.server_close); self.addCleanup(srv.shutdown)
        host = f"http://127.0.0.1:{srv.server_address[1]}"
        self.assertTrue(OllamaBackend("qwen2.5:7b", host).health())
        self.assertFalse(OllamaBackend("llama3.1:8b", host).health())

    def test_unreachable_server_is_unhealthy_and_gateway_reports_unavailable(self):
        be = OllamaBackend("qwen2.5:7b", "http://127.0.0.1:1")
        self.assertFalse(be.health())
        from oracle_arc.types import ModelUnavailable
        with self.assertRaises(ModelUnavailable):
            ModelGateway([be]).chat(REQ)


class RemoteProtocolTests(unittest.TestCase):
    def setUp(self):
        self.srv, self.seen = serve(lambda m, p, b, h: (200, {
            "choices": [{"message": {"content": "remote hi"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}))
        self.addCleanup(self.srv.shutdown)
        os.environ["TEST_ARC_KEY"] = "sk-test-123"
        self.addCleanup(os.environ.pop, "TEST_ARC_KEY", None)
        self.be = OpenAICompatBackend("remote", f"http://127.0.0.1:{self.srv.server_address[1]}", "m1",
                                      "TEST_ARC_KEY", cost_per_1k=2.0)

    def test_request_shape_auth_header_usage_and_cost(self):
        r = self.be.chat(REQ)
        path, body, headers = self.seen[0]
        self.assertEqual(path, "/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer sk-test-123")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual((r.text, r.prompt_tokens, r.completion_tokens), ("remote hi", 10, 5))
        self.assertAlmostEqual(r.cost, 0.03)

    def test_missing_key_means_unhealthy_and_never_calls_out(self):
        del os.environ["TEST_ARC_KEY"]
        self.assertFalse(self.be.health())
        with self.assertRaises(RuntimeError):
            self.be.chat(REQ)
        self.assertEqual(self.seen, [])

    def test_remote_not_called_for_sensitive_data_even_when_enabled(self):
        g = ModelGateway([self.be], RoutingPolicy(allow_remote=True, remote_max_data_class=DataClass.PUBLIC))
        from oracle_arc.types import ModelUnavailable
        with self.assertRaises(ModelUnavailable):
            g.chat(ChatRequest([{"role": "user", "content": "my balance"}], data_class=DataClass.FINANCIAL))
        self.assertEqual(self.seen, [])


if __name__ == "__main__":
    unittest.main()
