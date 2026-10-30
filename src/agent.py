"""LLM-агент с подключаемыми механизмами контроля и протоколированием ошибок.

Разметка ошибок. Каждое действие агента (вызов инструмента или вариант итогового
ответа) сравнивается с эталоном задачи. Ошибочное действие порождает событие
{scenario, kind, detected_by}. detected_by — первый компонент, остановивший или
выявивший ошибку: IS (явный отказ информационной системы), data_control,
deterministic, restriction, verification, monitoring, confirmation; None — ошибка
не обнаружена. Исправленной считается обнаруженная ошибка в прогоне, который в
итоге завершился успешно.
"""
import json
import re
import time
from collections import Counter

from .configs import (MAX_ANSWER_CORRECTIONS, MAX_ITER_BASE, MAX_ITER_MONITOR, MAX_RETRIES,
                     MAX_VERIFIER_ROUNDS)
from .ticket_system import TicketSystem, brief
from .raw_llm import diagnose_tool_call, raw_generate
from .tools import (ALL_SPECS, CRITICAL, DETERMINISTIC_TOOL_SPECS, MUTATING, TOOL_SPECS, check_value, normalize,
                   to_ollama, transition_rule, validate_args)

SYSTEM_PROMPT = (
    "Ты — интеллектуальный агент службы технической поддержки. Ты работаешь с информационной системой "
    "управления заявками через предоставленные инструменты. Сегодня 29.09.2026.\n"
    "Выполняй запрос пользователя самостоятельно, не задавай уточняющих вопросов.\n"
    "Когда задача выполнена (или её невозможно выполнить), дай итоговый ответ — только JSON указанного "
    "формата, без пояснений и без markdown."
)
PROMPT_DET = ("\nДля проверки допустимости перевода заявки в другой статус используй check_status_transition — "
              "это детерминированная проверка по регламенту.")
PROMPT_RESTRICT = ("\nРегламент действий: перед изменением заявки получи сведения о ней (get_ticket или "
                   "search_tickets); перед созданием заявки выполни поиск дубликатов (search_tickets). "
                   "Действия, нарушающие регламент, будут отклонены.")
PROMPT_CONFIRM = "\nОперации создания и изменения заявок выполняются только после подтверждения пользователем."


def parse_json(text):
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                return dec.raw_decode(text[i:])[0]
            except ValueError:
                continue
    return None


STOPWORDS = {"не", "на", "для", "в", "у", "по", "и", "с", "со", "к", "от", "из", "работает", "снова", "срочно",
             "нового", "новой", "заявка", "заявку", "нет"}


def find_similar_open(tickets, description, category=None, min_shared=2):
    """Детерминированный поиск дубликатов: незакрытые заявки той же категории с ≥ min_shared общими
    значимыми словами описания."""
    words = lambda s: {w for w in re.findall(r"[a-zа-яё0-9]+", str(s).lower()) if len(w) >= 3 and w not in STOPWORDS}
    target = words(description)
    return [t for t in tickets.values() if t["status"] not in ("Выполнена", "Отменена")
            and (category is None or t["category"] == category)
            and len(words(t["description"]) & target) >= min_shared]


def keyword_search(tickets, args):
    """Поиск по основам значимых слов запроса (без учёта словоформ) с сохранением остальных фильтров."""
    stems = {w[:5] for w in re.findall(r"[a-zа-яё0-9]+", str(args.get("text", "")).lower())
             if (len(w) >= 3 or any(ch.isdigit() for ch in w)) and w not in STOPWORDS}
    if not stems:
        return []
    pool = [t for t in tickets.values()
            if all(args.get(k) in (None, t[k]) for k in ("assignee", "priority", "status"))]
    score = lambda t: sum(st in t["description"].lower() for st in stems)
    best = [t for t in pool if score(t) == len(stems)]
    if not best:
        need = max(1, (len(stems) + 1) // 2)
        best = sorted((t for t in pool if score(t) >= need), key=score, reverse=True)
    return sorted(best, key=lambda t: t["id"])


def call_key(name, args):
    return name + json.dumps(args, sort_keys=True, ensure_ascii=False)


def is_error(res):
    return isinstance(res, dict) and "error" in res


def is_incomplete(res):
    return isinstance(res, dict) and "result" in res and res["result"] is None


class RunContext:
    """Состояние одного прогона, доступное эталонным предикатам задач."""

    def __init__(self, is_):
        self.is_ = is_
        self.init = is_.snapshot()     # исходное состояние ИС для проверки «лишних» изменений
        self.executed = []          # (name, args, result)
        self.observed = set()
        self.created_ids = []
        self.searched = False
        self.successful_mut = set()
        self.attempts = Counter()
        self.incomplete_ids = set()
        self.pending_check = set()
        self.state_checked_after_incomplete = False

    def called_ok(self, name, tid):
        return any(n == name and a.get("ticket_id") == tid and not is_error(r) for n, a, r in self.executed)

    def count_calls(self, name):
        return sum(1 for n, _, _ in self.executed if n == name)


class Agent:
    def __init__(self, task, cfg, llm, seed):
        self.task, self.cfg, self.llm, self.seed = task, cfg, llm, seed
        self.is_ = TicketSystem(faults=task.faults, extra=task.extra_tickets)
        self.ctx = RunContext(self.is_)
        self.events, self.trace = [], []
        self.llm_calls = self.iterations = self.confirmations = self.false_alarms = self.auto_retries = 0
        self.llm_time = 0.0
        self.tokens = 0

        names = list(TOOL_SPECS) if not cfg.limit_tools else list(task.allowed_tools)
        if cfg.deterministic and ("change_status" in names or task.id == "T4"):
            names.append("check_status_transition")
        self.visible = names
        self.judge_allowed = set(task.allowed_tools) | set(DETERMINISTIC_TOOL_SPECS)

    def _chat(self, messages, tools=None, temperature=None):
        msg, st = self.llm.chat(messages, tools=tools, seed=self.seed, temperature=temperature)
        self.llm_calls += 1
        self.llm_time += st["wall"]
        self.tokens += st["prompt_tokens"] + st["output_tokens"]
        return msg

    def judge_call(self, name, args):
        """Эталонная оценка вызова: (сценарий, вид ошибки) или None."""
        t, c = self.task, self.ctx
        if name not in self.judge_allowed:
            return ("E4", "wrong_tool")
        if validate_args(name, args):
            return ("E5", "params")
        if name in MUTATING:
            key = call_key(name, args)
            if key in c.successful_mut:
                return ("E6", "repeat")
            if c.attempts[key] > MAX_RETRIES:
                return ("E6", "excess_retry")
            if t.requires_observation and args.get("ticket_id") not in c.observed:
                return ("E3", "plan")
            if not any(tool == name and pred(args, c) for tool, pred in t.expected):
                return (t.scenario, "wrong_action")
        return None

    def add_event(self, label, stage, detected_by):
        ev = {"scenario": label[0], "kind": label[1], "stage": stage, "detected_by": detected_by,
              "iteration": self.iterations}
        self.events.append(ev)
        return ev

    def policy_violation(self, name, args):
        """Ограничение набора инструментов и/или правила регламента (программная оболочка)."""
        c = self.ctx
        if self.cfg.limit_tools and name not in self.visible:
            return f"Инструмент {name} недоступен для данной задачи"
        if not self.cfg.check_rules:
            return None
        if name in MUTATING and name != "create_ticket" and args.get("ticket_id") not in c.observed:
            return "Нарушение регламента: перед изменением необходимо получить сведения о заявке (get_ticket)"
        if name == "create_ticket" and self.cfg.rules_v2:
            dups = find_similar_open(self.is_.tickets, args.get("description", ""), args.get("category"))
            if dups:
                listing = "; ".join(f"{t['id']} «{t['description']}» (статус {t['status']}, приоритет {t['priority']})"
                                    for t in dups)
                return ("Нарушение регламента: найдены похожие незакрытые заявки: " + listing + ". Если обращение "
                        "относится к существующей заявке, измени её вместо создания новой")
        if name == "create_ticket" and not c.searched:
            return "Нарушение регламента: перед созданием заявки необходимо выполнить поиск дубликатов (search_tickets)"
        if name == "change_status":
            t = self.is_.tickets.get(args.get("ticket_id"))
            if t is not None:
                ok, reason = transition_rule(t, args.get("new_status"))
                if not ok:
                    return "Нарушение регламента: " + reason
        return None

    def loop_violation(self, name, args):
        """Мониторинг: повтор выполненной операции, превышение лимита повторов, зацикливание."""
        key = call_key(name, args)
        if name in MUTATING and key in self.ctx.successful_mut:
            return "Операция уже успешно выполнена ранее, повтор не требуется"
        if self.ctx.attempts[key] > MAX_RETRIES:
            return "Превышен лимит повторов операции. Используй другие данные или заверши задачу"
        return None

    def post_verify(self, name, args, result):
        """Верификация состояния после изменяющей операции."""
        c = self.ctx
        if name == "create_ticket":
            tid = result.get("id") if isinstance(result, dict) else None
            t = self.is_.tickets.get(tid)
            if t is None:
                return "Проверка состояния: заявка в системе не найдена"
            diff = [f"{k}={t[k]!r} (ожидалось {v!r})" for k, v in args.items() if t.get(k) != v]
            return "Проверка состояния: " + ("заявка создана, поля совпадают" if not diff else "расхождения: " + "; ".join(diff))
        tid = args.get("ticket_id")
        t = self.is_.tickets.get(tid)
        if t is None:
            return None
        if tid in c.incomplete_ids:
            c.state_checked_after_incomplete = True
            c.pending_check.discard(tid)
        expect = {"change_status": {"status": args.get("new_status")},
                  "assign_ticket": {"assignee": args.get("assignee")},
                  "update_ticket": {k: v for k, v in args.items() if k != "ticket_id"}}.get(name)
        if name == "add_comment":
            ok = bool(t["comments"]) and t["comments"][-1]["text"] == args.get("text")
            return "Проверка состояния: комментарий " + ("добавлен" if ok else "НЕ добавлен")
        if expect is None:
            return None
        diff = [f"{k}: фактически {t.get(k)!r}, ожидалось {v!r}" for k, v in expect.items() if t.get(k) != v]
        return ("Проверка состояния: изменение подтверждено" if not diff else
                "Проверка состояния: изменение НЕ применено (" + "; ".join(diff) + ")")

    def handle_call(self, name, raw_args):
        cfg, c = self.cfg, self.ctx
        args = dict(raw_args) if isinstance(raw_args, dict) else (parse_json(str(raw_args)) or {})
        label = self.judge_call(name, args)
        ev = self.add_event(label, "action", None) if label else None
        step = {"it": self.iterations, "tool": name, "args": args}

        def block(by, message):
            if ev:
                ev["detected_by"] = by
            else:
                self.false_alarms += 1
            step.update(blocked_by=by, result=message)
            self.trace.append(step)
            return {"error": "REJECTED", "by": by, "message": message}

        if cfg.deterministic and cfg.has("normalize"):
            norm = normalize(args)
            if norm != args:
                step["normalized"] = norm
                if ev and ev["kind"] == "params" and not validate_args(name, norm):
                    ev["detected_by"] = "deterministic"
                    rest = self.judge_call(name, norm)   # нормализация устранила только ошибку формата
                    if rest:
                        ev = self.add_event(rest, "action", None)
                    else:
                        ev = None
                args = norm
        if cfg.data_control and cfg.has("schema") and name in TOOL_SPECS:
            problems = validate_args(name, args)
            if problems:
                allowed = ", ".join(f"{k}{' (обяз.)' if k in TOOL_SPECS[name]['required'] else ''}"
                                    for k in TOOL_SPECS[name]["params"])
                return block("data_control", "Вызов не выполнен, параметры не прошли проверку: " +
                             "; ".join(problems) + f". Допустимые параметры {name}: {allowed}")
        if cfg.limit_tools or cfg.check_rules:
            v = self.policy_violation(name, args)
            if v:
                return block("restriction", v)
        if cfg.monitor and cfg.has("loopblock"):
            v = self.loop_violation(name, args)
            if v:
                return block("monitoring", v)
        if cfg.confirm and name in CRITICAL:
            self.confirmations += 1
            if ev is not None:   # имитация пользователя, знающего цель запроса
                return block("confirmation", f"Пользователь отклонил операцию {name}"
                             f"({json.dumps(args, ensure_ascii=False)}): она не соответствует запросу. "
                             "Операция не выполнена.")

        key = call_key(name, args)
        c.attempts[key] += 1
        if name == "check_status_transition":
            t = self.is_.tickets.get(args.get("ticket_id"))
            if t is None:
                result = {"error": "NOT_FOUND"}
            else:
                ok, reason = transition_rule(t, args.get("new_status"))
                result = {"allowed": ok, "reason": reason, "current_status": t["status"],
                          "review_status": t["review_status"]}
                c.observed.add(t["id"])
        elif name == "search_tickets" and cfg.deterministic and "page" not in args:
            # детерминированная функция: полная выборка без постраничной разбивки
            first = self.is_.call(name, args)
            items, page = list(first.get("items", [])), 1
            while first.get("has_more"):
                page += 1
                first = self.is_.op_search_tickets(**{**args, "page": page})
                items += first["items"]
            result = {"items": items, "total": len(items), "has_more": False}
        else:
            result = self.is_.call(name, args)
        if (name == "search_tickets" and cfg.deterministic and cfg.has("keyword") and args.get("text") and not is_error(result)
                and not result.get("items")):
            # детерминированная функция: при пустом результате поиска по тексту — поиск по основам ключевых слов
            found = keyword_search(self.is_.tickets, args)
            if found:
                result = {"items": [brief(t) for t in found], "total": len(found), "has_more": False,
                          "note": "Точное совпадение текста не найдено; записи найдены по ключевым словам запроса"}
                step["keyword_fallback"] = True
        # мониторинг: временный отказ повторяется оболочкой автоматически (не более MAX_RETRIES раз)
        retries = 0
        while cfg.monitor and cfg.has("autoretry") and is_error(result) and result.get("error") == "SERVICE_UNAVAILABLE" \
                and retries < MAX_RETRIES:
            c.executed.append((name, args, result))
            retries += 1
            self.auto_retries += 1
            result = self.is_.call(name, args)
        if retries:
            step["auto_retries"] = retries
        c.executed.append((name, args, result))

        if is_error(result) and ev and ev["detected_by"] is None:
            # явный отказ ИС: механизмом агента считается, только если его разобрал мониторинг
            ev["detected_by"] = "monitoring" if cfg.monitor else "IS"
        # учёт наблюдаемых записей
        if name == "search_tickets":
            c.searched = True
            c.observed.update(x["id"] for x in result.get("items", []))
        if name == "get_ticket" and not is_error(result):
            tid = args.get("ticket_id")
            c.observed.add(tid)
            if tid in c.incomplete_ids:
                c.state_checked_after_incomplete = True
                c.pending_check.discard(tid)
        if name == "create_ticket" and not is_error(result) and not is_incomplete(result):
            c.created_ids.append(result["id"])
            c.observed.add(result["id"])
        if name in MUTATING:
            if is_incomplete(result):
                c.incomplete_ids.add(args.get("ticket_id"))
            elif not is_error(result):
                c.successful_mut.add(key)

        out = dict(result) if isinstance(result, dict) else {"result": result}
        if cfg.monitor:
            if step.get("auto_retries") and not is_error(result):
                out["monitor"] = (f"После временного отказа сервиса операция автоматически повторена "
                                  f"({step['auto_retries']}) и выполнена.")
            elif is_error(result) and result.get("error") == "SERVICE_UNAVAILABLE":
                out["monitor"] = "Сервис недоступен: лимит автоматических повторов исчерпан. Операция не выполнена."
            elif is_incomplete(result):
                c.pending_check.add(args.get("ticket_id"))
                out["monitor"] = ("Ответ системы неполный: результат операции неизвестен. Перед продолжением "
                                  "проверь фактическое состояние записи через get_ticket.")
            elif is_error(result):
                out["monitor"] = ("Операция отклонена системой. Не повторяй вызов с теми же параметрами — "
                                  "исправь параметры или выбери другое действие.")
        if cfg.verify and name in MUTATING and not is_error(result):
            note = self.post_verify(name, args, result)
            if note:
                out["state_check"] = note
        step["result"] = out
        self.trace.append(step)
        return out

    def diagnose_malformed_call(self, history, tools):
        """Контроль данных: «сырой» текст отброшенного вызова → конкретное сообщение об ошибке по схеме."""
        options = dict(self.llm.options, seed=self.seed)
        t0 = time.perf_counter()
        raw = raw_generate(self.llm.model, history, tools, options)
        self.llm_calls += 1
        self.llm_time += time.perf_counter() - t0
        call, err = diagnose_tool_call(raw)
        if not call or not err:
            return None
        name = (re.search(r'"name"\s*:\s*"(\w+)"', call) or [None, ""])[1]
        hint = ""
        m = re.search(r'"(\w+)"\s*:\s*"[^"]*"\s*,\s*"[^"]*"\s*(?=[,}])', call)
        spec = ALL_SPECS.get(name, {}).get("params", {})
        if m and m.group(1) in spec:
            hint = (f" Параметр {m.group(1)} инструмента {name} принимает одно значение типа "
                    f"{spec[m.group(1)].get('type', 'string')}; для нескольких значений выполни отдельные вызовы "
                    f"или не указывай этот параметр.")
        return (f"Вызов инструмента {name} не выполнен: аргументы сформированы с синтаксической ошибкой JSON — {err}."
                f"{hint} Операция НЕ выполнена; повтори вызов с корректными аргументами.")

    def llm_verify(self, draft):
        touched = set(self.ctx.observed) | {a.get("ticket_id") for _, a, _ in self.ctx.executed}
        state = {tid: {k: v for k, v in self.is_.tickets[tid].items() if k != "history"}
                 for tid in sorted(x for x in touched if x in self.is_.tickets)}
        log = "\n".join(f"- {n}({json.dumps(a, ensure_ascii=False)}) -> {json.dumps(r, ensure_ascii=False)[:400]}"
                        for n, a, r in self.ctx.executed) or "(вызовов не было)"
        prompt = ("Ты — модуль проверки результата работы агента. Проверь, соответствует ли итоговый ответ агента "
                  "запросу пользователя и фактическим данным информационной системы (учитывай все условия запроса).\n\n"
                  f"Запрос пользователя:\n{self.task.prompt}\n\nВызовы инструментов и ответы системы:\n{log}\n\n"
                  f"Фактическое состояние затронутых заявок:\n{json.dumps(state, ensure_ascii=False)}\n\n"
                  f"Итоговый ответ агента:\n{json.dumps(draft, ensure_ascii=False)}\n\n"
                  'Верни только JSON: {"ok": true|false, "issues": "расхождения или пустая строка"}')
        msg = self._chat([{"role": "user", "content": prompt}], temperature=0.0)
        v = parse_json(msg.get("content", ""))
        if not isinstance(v, dict):
            return True, ""
        return v.get("ok") is not False, str(v.get("issues", ""))

    def answer_problems(self, draft):
        """Контроль данных для итогового ответа: схема + согласованность с источником."""
        problems = check_value(self.task.answer_schema, draft, "ответ")
        src = self.task.source_text
        if src and isinstance(draft, dict):
            ids = [draft.get("ticket_id")] if "ticket_id" in draft else \
                [x.get("ticket_id") for x in draft.get("tickets", []) if isinstance(x, dict)]
            for tid in ids:
                if isinstance(tid, str) and tid not in src:
                    problems.append(f"идентификатор {tid} отсутствует в исходном тексте")
            if len(ids) != len(set(map(str, ids))):
                problems.append("идентификаторы заявок повторяются")
        elif isinstance(draft, dict):
            # согласованность с ИС: идентификаторы в ответе должны быть получены от системы
            known = self.ctx.observed | set(self.ctx.created_ids)
            ids = [draft.get("ticket_id")] + list(draft.get("ticket_ids") or [])
            for tid in ids:
                if isinstance(tid, str) and tid and tid not in known:
                    problems.append(f"заявка {tid} не подтверждена данными информационной системы" + (
                        ": ни одна выполненная операция не создала и не вернула эту заявку; выполни необходимые "
                        "действия с помощью инструментов, а не сообщай результат без их вызова"
                        if self.cfg.data_v2 else ""))
        return problems

    def run(self):
        cfg, task = self.cfg, self.task
        t0 = time.perf_counter()
        system = SYSTEM_PROMPT + (PROMPT_DET if cfg.deterministic else "") + \
            (PROMPT_RESTRICT if cfg.check_rules else "") + (PROMPT_CONFIRM if cfg.confirm else "")
        fmt = f"\n\nФормат итогового ответа (JSON): {task.answer_example}"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": task.prompt + fmt}]
        tools = to_ollama(self.visible) if self.visible else None
        max_iter = MAX_ITER_MONITOR if cfg.monitor else MAX_ITER_BASE
        answer, corrections, verifier_rounds, stop_reason = None, 0, 0, "iteration_limit"

        while self.iterations < max_iter:
            self.iterations += 1
            msg = self._chat(messages, tools=tools)
            calls = msg.get("tool_calls") or []
            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls} if calls
                            else {"role": "assistant", "content": msg.get("content", "")})
            if calls:
                for tc in calls:
                    fn = tc.get("function", {})
                    res = self.handle_call(fn.get("name", ""), fn.get("arguments", {}))
                    messages.append({"role": "tool", "tool_name": fn.get("name", ""),
                                     "content": json.dumps(res, ensure_ascii=False)})
                continue

            draft = parse_json(msg.get("content", ""))
            self.trace.append({"it": self.iterations, "answer": draft, "raw": None if draft else msg.get("content", "")[:300]})
            if draft is None:
                # Пустой ответ без вызова = вызов инструмента с невалидным JSON, отброшенный Ollama.
                empty = not (msg.get("content") or "").strip()
                label = ("E5", "malformed_call") if empty else (task.scenario, "format")
                by = "data_control" if cfg.data_control else "monitoring" if cfg.monitor else None
                if by and corrections < MAX_ANSWER_CORRECTIONS:
                    corrections += 1
                    self.add_event(label, "answer", by)
                    feedback = None
                    if empty and cfg.data_v2 and cfg.has("diagnosis"):
                        feedback = self.diagnose_malformed_call(messages[:-1], tools)
                        if feedback:
                            self.trace[-1]["diagnosis"] = feedback[:300]
                    messages.append({"role": "user", "content": (feedback or
                                     "Ответ пустой или не распознан: вероятно, вызов инструмента сформирован "
                                     "некорректно (невалидный JSON аргументов), поэтому операция НЕ выполнена. "
                                     "Повтори действие с корректными аргументами либо, если задача уже выполнена, "
                                     "верни итоговый ответ строго в формате JSON.") + fmt})
                    continue
                self.add_event(label, "answer", None)
                stop_reason = "malformed_output"
                break

            original = draft
            if cfg.deterministic and cfg.has("normalize"):
                draft = normalize(draft)
                if draft != original and not task.answer_ok(original, self.ctx) and task.answer_ok(draft, self.ctx):
                    self.add_event((task.scenario, "answer"), "answer", "deterministic")

            feedback, by = [], None
            if cfg.monitor and cfg.has("pending") and self.ctx.pending_check:
                feedback.append("Результат операции над " + ", ".join(sorted(self.ctx.pending_check)) +
                                " не установлен: проверь фактическое состояние записи через get_ticket.")
                by = "monitoring"
            if not feedback and cfg.data_control:
                probs = self.answer_problems(draft)
                if probs:
                    feedback.append("Итоговый ответ не прошёл проверку данных: " + "; ".join(probs))
                    by = "data_control"
            if not feedback and cfg.verify and verifier_rounds < MAX_VERIFIER_ROUNDS:
                verifier_rounds += 1
                ok, issues = self.llm_verify(draft)
                if not ok:
                    feedback.append("Проверка результата выявила расхождения: " + issues)
                    by = "verification"

            if feedback and corrections < MAX_ANSWER_CORRECTIONS:
                corrections += 1
                if not task.answer_ok(draft, self.ctx) or not task.state_ok(self.is_.tickets, self.ctx):
                    self.add_event((task.scenario, "answer"), "answer", by)
                    if by == "verification":   # проверка выявила и последствия ранее незамеченных действий
                        for e in self.events:
                            if e["detected_by"] is None:
                                e["detected_by"] = "verification"
                else:
                    self.false_alarms += 1
                self.trace[-1]["rejected_by"] = by
                self.trace[-1]["feedback"] = " ".join(feedback)[:500]
                messages.append({"role": "user", "content": " ".join(feedback) + " Исправь и заверши задачу." + fmt})
                continue
            answer, stop_reason = draft, "answer"
            break

        answer_ok = answer is not None and bool(task.answer_ok(answer, self.ctx))
        state_ok = bool(task.state_ok(self.is_.tickets, self.ctx))
        success = answer_ok and state_ok
        if answer is not None and not answer_ok:
            self.add_event((task.scenario, "answer"), "answer", None)
        if answer is None and stop_reason == "iteration_limit":
            self.add_event((task.scenario, "no_answer"), "answer",
                           "monitoring" if cfg.monitor and stop_reason == "iteration_limit" else None)
        if answer is not None and answer_ok and not state_ok and not any(e["detected_by"] is None for e in self.events):
            self.add_event((task.scenario, "state"), "answer", None)

        return {
            "success": success, "answer_ok": answer_ok, "state_ok": state_ok, "stop_reason": stop_reason,
            "answer": answer, "time_s": round(time.perf_counter() - t0, 3), "llm_time_s": round(self.llm_time, 3),
            "llm_calls": self.llm_calls, "iterations": self.iterations, "tokens": self.tokens,
            "tool_calls": len(self.ctx.executed), "confirmations": self.confirmations,
            "false_alarms": self.false_alarms, "auto_retries": self.auto_retries, "events": self.events,
            "error_events": len(self.events),
            # N_обн — выявлено механизмами контроля агента (отказы ИС сюда не входят)
            "detected": sum(1 for e in self.events if e["detected_by"] not in (None, "IS")),
            # N_испр — обнаруженные ошибки, после которых выполнение восстановлено (прогон успешен)
            "corrected": sum(1 for e in self.events if e["detected_by"] not in (None, "IS")) if success else 0,
            "trace": self.trace,
        }
