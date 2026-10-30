"""Получение «сырого» текста генерации в обход разбора вызовов инструментов Ollama.

Ollama молча отбрасывает вызов инструмента с синтаксически неверным JSON, и оболочка агента получает
пустой ответ. Для диагностики запрос повторно формируется по шаблону чата Qwen3 (как в Ollama) и
отправляется в /api/generate с raw=true; из ответа извлекается текст вызова и описание ошибки.
"""
import json
import re
import urllib.request

GENERATE_URL = "http://localhost:11434/api/generate"


def render_qwen3(messages, tools):
    """Повторяет шаблон чата qwen3 из Ollama (режим рассуждений отключён)."""
    out = []
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    sys_txt = "<|im_start|>system\n" + system
    if tools:
        sys_txt += ("\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
                    "You are provided with function signatures within <tools></tools> XML tags:\n<tools>")
        for t in tools:
            sys_txt += "\n" + json.dumps({"type": "function", "function": t["function"]}, ensure_ascii=False)
        sys_txt += ("\n</tools>\n\nFor each function call, return a json object with function name and arguments "
                    "within <tool_call></tool_call> XML tags:\n<tool_call>\n{\"name\": <function-name>, "
                    "\"arguments\": <args-json-object>}\n</tool_call>")
    out.append(sys_txt + "<|im_end|>\n")
    msgs = [m for m in messages if m["role"] != "system"]
    last_user = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=-1)
    for i, m in enumerate(msgs):
        if m["role"] == "user":
            out.append("<|im_start|>user\n" + m["content"] + (" /no_think" if i == last_user else "") + "<|im_end|>\n")
        elif m["role"] == "assistant":
            body = m.get("content") or ""
            if not body and m.get("tool_calls"):
                body = "<tool_call>\n" + "".join(
                    json.dumps({"name": c["function"]["name"], "arguments": c["function"]["arguments"]},
                               ensure_ascii=False) + "\n" for c in m["tool_calls"]) + "</tool_call>"
            out.append("<|im_start|>assistant\n" + body + "<|im_end|>\n")
        elif m["role"] == "tool":
            out.append("<|im_start|>user\n<tool_response>\n" + m["content"] + "\n</tool_response><|im_end|>\n")
    out.append("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    return "".join(out)


def raw_generate(model, messages, tools, options):
    body = {"model": model, "prompt": render_qwen3(messages, tools), "raw": True, "stream": False,
            "options": {**options, "num_predict": 400}}
    req = urllib.request.Request(GENERATE_URL, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "")


def diagnose_tool_call(raw_text):
    """Возвращает (текст вызова, описание ошибки) для некорректного вызова инструмента или (None, None)."""
    m = re.search(r"<tool_call>\s*(.*?)\s*(</tool_call>|$)", raw_text, re.S)
    if not m:
        return None, None
    call = m.group(1).strip()
    try:
        json.loads(call)
        return call, None
    except json.JSONDecodeError as e:
        return call, f"{e.msg} (позиция {e.pos}: «…{call[max(0, e.pos - 40):e.pos + 10]}…»)"
