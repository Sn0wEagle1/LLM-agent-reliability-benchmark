"""Минимальный клиент Ollama /api/chat (без внешних зависимостей)."""
import json
import time
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/chat"


class LLM:
    def __init__(self, model, temperature=0.7, top_p=0.8, num_ctx=8192, think=False):
        self.model = model
        self.options = {"temperature": temperature, "top_p": top_p, "top_k": 20, "num_ctx": num_ctx}
        self.think = think

    def chat(self, messages, tools=None, seed=None, temperature=None):
        """Возвращает (message, stats). stats: время, число токенов."""
        options = dict(self.options)
        if seed is not None:
            options["seed"] = seed
        if temperature is not None:
            options["temperature"] = temperature
        body = {"model": self.model, "messages": messages, "stream": False,
                "think": self.think, "options": options}
        if tools:
            body["tools"] = tools
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        for attempt in range(3):
            try:
                t0 = time.perf_counter()
                req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=600) as r:
                    resp = json.loads(r.read().decode("utf-8"))
                stats = {"wall": time.perf_counter() - t0,
                         "prompt_tokens": resp.get("prompt_eval_count", 0),
                         "output_tokens": resp.get("eval_count", 0)}
                return resp["message"], stats
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == 2:
                    raise
                time.sleep(3)
