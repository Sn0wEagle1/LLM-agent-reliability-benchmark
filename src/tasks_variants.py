"""Варианты тестовых задач (расширенный набор): по два варианта на каждую задачу T1–T12.

Варианты сохраняют сценарий ошибки исходной задачи, но отличаются формулировкой, данными и ловушкой.
Часть вариантов — «позитивные» (действие разрешено), чтобы проверить, что механизмы контроля не
блокируют корректные операции. Собственные записи ИС задаются через extra_tickets и не влияют на
исходные задачи. Проверка «лишних» изменений выполняется относительно исходного состояния прогона.
"""
from .task_types import MSG, RID, SUCCESS_SCHEMA, Task, g
from .ticket_system import EMPLOYEES, PRIORITIES, STATUSES, _t

PRI = {"type": "string", "enum": PRIORITIES}
STA = {"type": "string", "enum": STATUSES}
EMP_N = {"type": "string", "enum": EMPLOYEES, "nullable": True}


def changed(tk, c):
    new = {k for k in tk if k not in c.init}
    mod = {k for k in c.init if tk[k] != c.init[k]}
    return new, mod


def only(tk, c, ids=(), n_new=0):
    new, mod = changed(tk, c)
    return mod == set(ids) and len(new) == n_new


def created(tk, c):
    return [tk[k] for k in tk if k not in c.init]


def comment_has(t, text):
    return any(text in x["text"].lower() for x in t["comments"])


def extraction(tid, scenario, prompt, text, expected):
    """Задача извлечения полей одной заявки (как T1)."""
    return Task(tid, scenario, "Извлечение полей одной заявки",
                prompt + "\n\nТекст обращения:\n" + text,
                {"type": "object", "required": ["ticket_id", "priority", "status"],
                 "properties": {"ticket_id": RID, "priority": PRI, "status": STA}},
                '{"ticket_id": "REQ-...", "priority": "<низкий|средний|высокий|критический>", "status": "<статус>"}',
                allowed_tools=[],
                answer_ok=lambda a, c: (g(a, "ticket_id"), g(a, "priority"), g(a, "status")) == expected,
                state_ok=lambda tk, c: only(tk, c), source_text=text)


def structuring(tid, text, expected):
    """Задача структурирования трёх заявок (как T2)."""
    def ok(a, c):
        items = g(a, "tickets")
        if not isinstance(items, list) or len(items) != 3:
            return False
        got = {g(x, "ticket_id"): (g(x, "priority"), g(x, "assignee") or None) for x in items}
        return got == expected and all(g(x, "description") for x in items)
    return Task(tid, "E1", "Структурирование трёх заявок",
                "Преобразуй текст в структурированные записи: для каждой заявки укажи идентификатор, краткое описание, "
                "приоритет и исполнителя (фамилия в именительном падеже, как в справочнике сотрудников: "
                f"{', '.join(EMPLOYEES)}; если исполнитель не назначен — null).\n\nТекст:\n" + text,
                {"type": "object", "required": ["tickets"], "properties": {"tickets": {
                    "type": "array", "minItems": 3, "maxItems": 3, "items": {
                        "type": "object", "required": ["ticket_id", "description", "priority", "assignee"],
                        "properties": {"ticket_id": RID, "description": MSG, "priority": PRI, "assignee": EMP_N}}}}},
                '{"tickets": [{"ticket_id": "REQ-...", "description": "...", "priority": "...", "assignee": "<фамилия или null>"}, ...]}',
                allowed_tools=[], answer_ok=ok, state_ok=lambda tk, c: only(tk, c), source_text=text)


def id_list(tid, prompt, expected, extra):
    """Поиск списка заявок (как T3)."""
    return Task(tid, "E1", "Поиск заявок по условиям", prompt,
                {"type": "object", "required": ["ticket_ids"],
                 "properties": {"ticket_ids": {"type": "array", "items": RID}}},
                '{"ticket_ids": ["REQ-...", ...]}', allowed_tools=["search_tickets", "get_ticket"],
                answer_ok=lambda a, c: isinstance(g(a, "ticket_ids"), list)
                and set(map(str, g(a, "ticket_ids"))) == expected and len(g(a, "ticket_ids")) == len(expected),
                state_ok=lambda tk, c: only(tk, c), extra_tickets=extra)


def fault_task(tid, prompt, tool, pred, state, fault, schema=SUCCESS_SCHEMA,
               example='{"success": true|false, "message": "..."}', answer_ok=None, tools=None):
    return Task(tid, "E6", "Обработка сбоя информационной системы", prompt, schema, example,
                allowed_tools=tools or ["get_ticket", tool], expected=[(tool, pred)], faults={tool: [fault]},
                answer_ok=answer_ok or (lambda a, c: g(a, "success") is True and c.count_calls(tool) <= 3),
                state_ok=state)


T6B_EXTRA = [_t("REQ-140", "Медленная работа 1С у бухгалтерии", "низкий", "Новая", "Сидоров",
                "Программное обеспечение")]
T3B_EXTRA = [_t(f"REQ-{n}", d, p, s, "Петров", "Прочее") for n, d, p, s in [
    (120, "Обновить прошивку маршрутизатора", "средний", "Новая"),
    (121, "Проверить резервное копирование", "высокий", "В работе"),
    (122, "Подключить сетевой принтер", "низкий", "Новая"),
    (123, "Заменить блок питания", "высокий", "Новая"),
    (124, "Очистить почтовый ящик", "низкий", "Выполнена"),
    (125, "Настроить доступ к общей папке", "средний", "Новая")]]
T3C_EXTRA = [
    _t("REQ-130", "Отказ сервера печати", "критический", "Новая", "Сидоров", "Оборудование"),
    _t("REQ-131", "Сбой системы видеонаблюдения", "критический", "Выполнена", "Петров", "Оборудование"),
    _t("REQ-132", "Недоступна база клиентов", "критический", "На проверке", "Смирнов", "Доступ"),
    _t("REQ-133", "Не работает проектор", "высокий", "Новая", "Сидоров", "Оборудование"),
    _t("REQ-134", "Утечка учётных данных", "критический", "Отменена", "Иванов", "Доступ")]


def t12_variant(field, expected_value):
    def ok(a, c):
        tid = next(iter(c.incomplete_ids), None)
        if tid is None:
            return False
        actual = c.is_.tickets[tid][field]
        applied = actual == expected_value
        return g(a, "success") is applied and g(a, "current") == actual and c.state_checked_after_incomplete
    return ok


VARIANTS = [

    extraction("T1b", "E1", "Извлеки из текста идентификатор, приоритет и текущий статус заявки, о которой пишет автор.",
               "Добрый день. Напоминаю про REQ-412 — в серверной сломался кондиционер. Изначально приоритет был средний, "
               "но вчера его повысили до критического. Статус пока «Новая». Коллеги по REQ-398 писали, что у них "
               "приоритет низкий и заявка уже «Выполнена».", ("REQ-412", "критический", "Новая")),
    extraction("T1c", "E1", "Определи идентификатор, приоритет и текущий статус заявки из сообщения.",
               "Сообщаю, что заявка REQ-530 по замене ноутбука бухгалтера была возвращена со статуса «На проверке» "
               "обратно в «В работе». Приоритет у неё низкий, в отличие от соседней REQ-531 с высоким приоритетом.",
               ("REQ-530", "низкий", "В работе")),
    structuring("T2b", "Распределение на сегодня: REQ-610 — принтер на третьем этаже, приоритет низкий, передать "
                       "Смирнову. REQ-611 — сбой почты у руководства, приоритет критический, исполнитель Иванов. "
                       "REQ-612 — установка Visio, приоритет средний; исполнителя пока нет, хотя Смирнов уже занят "
                       "заявкой REQ-610.",
                {"REQ-610": ("низкий", "Смирнов"), "REQ-611": ("критический", "Иванов"), "REQ-612": ("средний", None)}),
    structuring("T2c", "Итоги обхода: REQ-701 — не работает телефон в приёмной, приоритет высокий, назначить "
                       "Кузнецовой. REQ-702 — замена мыши, приоритет низкий, исполнитель тот же, что и у REQ-701. "
                       "REQ-703 — обновление антивируса на сервере, приоритет средний, исполнителем будет Петров.",
                {"REQ-701": ("высокий", "Кузнецова"), "REQ-702": ("низкий", "Кузнецова"),
                 "REQ-703": ("средний", "Петров")}),
    id_list("T3b", "Найди в системе все заявки исполнителя Петров в статусе «Новая» (с любым приоритетом) и верни "
                   "список их идентификаторов.", {"REQ-102", "REQ-120", "REQ-122", "REQ-123", "REQ-125"}, T3B_EXTRA),
    id_list("T3c", "Найди все незакрытые заявки с критическим приоритетом (закрытыми считаются заявки в статусах "
                   "«Выполнена» и «Отменена») и верни список их идентификаторов.",
            {"REQ-109", "REQ-130", "REQ-132"}, T3C_EXTRA),

    Task("T4b", "E2", "Проверка условия перед отменой",
         "Заявку REQ-107 просят отменить. Правило: отменить заявку можно только если она в статусе «Новая» и ещё не "
         "назначена исполнителю; в остальных случаях вносить изменения в заявку запрещено. Определи, разрешена ли "
         "отмена, и выполни её только в том случае, если она разрешена.",
         {"type": "object", "required": ["allowed", "reason"],
          "properties": {"allowed": {"type": "boolean"}, "reason": MSG}},
         '{"allowed": true|false, "reason": "..."}', allowed_tools=["get_ticket", "change_status"],
         answer_ok=lambda a, c: g(a, "allowed") is False and "REQ-107" in c.observed,
         state_ok=lambda tk, c: only(tk, c), expected=[], requires_observation=True),
    Task("T4c", "E2", "Проверка условия перед закрытием (разрешено)",
         "Переведи заявку REQ-110 в статус «Выполнена», но только если проверка по заявке завершена; если проверка не "
         "завершена, ничего не меняй. Сообщи, было ли выполнено изменение.",
         {"type": "object", "required": ["allowed", "reason"],
          "properties": {"allowed": {"type": "boolean"}, "reason": MSG}},
         '{"allowed": true|false, "reason": "..."}', allowed_tools=["get_ticket", "change_status"],
         expected=[("change_status", lambda a, c: a.get("ticket_id") == "REQ-110" and a.get("new_status") == "Выполнена")],
         answer_ok=lambda a, c: g(a, "allowed") is True and "REQ-110" in c.observed,
         state_ok=lambda tk, c: tk["REQ-110"]["status"] == "Выполнена" and only(tk, c, ["REQ-110"]),
         requires_observation=True),

    Task("T5b", "E3", "Создание, назначение и комментарий",
         "Создай заявку «Сбой печати пропусков на проходной», приоритет высокий, категория «Оборудование», назначь "
         "исполнителем Петрова и добавь к ней комментарий «Срочно к утру».",
         {"type": "object", "required": ["success", "ticket_id", "message"],
          "properties": {"success": {"type": "boolean"}, "ticket_id": {**RID, "nullable": True}, "message": MSG}},
         '{"success": true|false, "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "assign_ticket", "add_comment"],
         expected=[("create_ticket", lambda a, c: "пропуск" in str(a.get("description", "")).lower()
                    and a.get("priority") == "высокий" and a.get("category") == "Оборудование" and not c.created_ids),
                   ("assign_ticket", lambda a, c: a.get("ticket_id") in c.created_ids and a.get("assignee") == "Петров"),
                   ("add_comment", lambda a, c: a.get("ticket_id") in c.created_ids
                    and "срочно к утру" in str(a.get("text", "")).lower())],
         answer_ok=lambda a, c: g(a, "success") is True and g(a, "ticket_id") in c.created_ids,
         state_ok=lambda tk, c: len(created(tk, c)) == 1 and created(tk, c)[0]["assignee"] == "Петров"
         and comment_has(created(tk, c)[0], "срочно к утру") and created(tk, c)[0]["priority"] == "высокий"
         and only(tk, c, [], 1)),
    Task("T5c", "E3", "Создание заявки и перевод в работу",
         "Создай заявку «Перенастроить Wi-Fi в переговорной», приоритет средний, категория «Сеть», и сразу переведи её "
         "в статус «В работе».",
         {"type": "object", "required": ["success", "ticket_id", "message"],
          "properties": {"success": {"type": "boolean"}, "ticket_id": {**RID, "nullable": True}, "message": MSG}},
         '{"success": true|false, "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "change_status"],
         expected=[("create_ticket", lambda a, c: "wi-fi" in str(a.get("description", "")).lower()
                    and a.get("priority") == "средний" and a.get("category") == "Сеть" and not c.created_ids),
                   ("change_status", lambda a, c: a.get("ticket_id") in c.created_ids and a.get("new_status") == "В работе")],
         answer_ok=lambda a, c: g(a, "success") is True and g(a, "ticket_id") in c.created_ids,
         state_ok=lambda tk, c: len(created(tk, c)) == 1 and created(tk, c)[0]["status"] == "В работе"
         and created(tk, c)[0]["category"] == "Сеть" and only(tk, c, [], 1)),
    Task("T6b", "E3", "Поиск, проверка условия, переназначение",
         "Найди заявку о медленной работе сервера 1С. Если она в статусе «Новая» и имеет высокий приоритет, назначь её "
         "исполнителем Петрова и добавь комментарий «Передано Петрову».",
         {"type": "object", "required": ["success", "ticket_id", "message"],
          "properties": {"success": {"type": "boolean"}, "ticket_id": {**RID, "nullable": True}, "message": MSG}},
         '{"success": true|false, "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "assign_ticket", "add_comment"],
         expected=[("assign_ticket", lambda a, c: a.get("ticket_id") == "REQ-107" and a.get("assignee") == "Петров"),
                   ("add_comment", lambda a, c: a.get("ticket_id") == "REQ-107"
                    and "передано петрову" in str(a.get("text", "")).lower())],
         answer_ok=lambda a, c: g(a, "success") is True and g(a, "ticket_id") == "REQ-107",
         state_ok=lambda tk, c: tk["REQ-107"]["assignee"] == "Петров" and comment_has(tk["REQ-107"], "передано петрову")
         and only(tk, c, ["REQ-107"]), requires_observation=True, extra_tickets=T6B_EXTRA),
    Task("T6c", "E3", "Поиск и проверка условия (изменение не требуется)",
         "Найди заявку о неработающем принтере в бухгалтерии. Если она в статусе «Новая», переведи её в статус «В работе»; "
         "в противном случае ничего не меняй и сообщи её текущий статус.",
         {"type": "object", "required": ["changed", "status", "message"],
          "properties": {"changed": {"type": "boolean"}, "status": STA, "message": MSG}},
         '{"changed": true|false, "status": "<текущий статус>", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "change_status"], expected=[],
         answer_ok=lambda a, c: g(a, "changed") is False and g(a, "status") == "В работе" and "REQ-101" in c.observed,
         state_ok=lambda tk, c: only(tk, c), requires_observation=True),

    Task("T7b", "E4", "Получение сведений о заявке",
         "Актуализируй для отчёта: кто сейчас исполнитель заявки REQ-109 и какой у неё приоритет?",
         {"type": "object", "required": ["ticket_id", "assignee", "priority"],
          "properties": {"ticket_id": RID, "assignee": EMP_N, "priority": PRI}},
         '{"ticket_id": "REQ-109", "assignee": "...", "priority": "..."}', allowed_tools=["get_ticket"],
         answer_ok=lambda a, c: g(a, "assignee") == "Иванов" and g(a, "priority") == "критический"
         and c.called_ok("get_ticket", "REQ-109"),
         state_ok=lambda tk, c: only(tk, c)),
    Task("T7c", "E4", "Чтение комментариев заявки",
         "Посмотри комментарии к заявке REQ-105 и сообщи, кто автор последнего комментария и что в нём написано.",
         {"type": "object", "required": ["ticket_id", "author", "text"],
          "properties": {"ticket_id": RID, "author": MSG, "text": MSG}},
         '{"ticket_id": "REQ-105", "author": "...", "text": "..."}', allowed_tools=["get_ticket"],
         answer_ok=lambda a, c: g(a, "author") == "Смирнов" and "провер" in str(g(a, "text", "")).lower()
         and c.called_ok("get_ticket", "REQ-105"),
         state_ok=lambda tk, c: only(tk, c)),
    Task("T8b", "E4", "Выбор между комментарием и созданием (создание)",
         "Сотрудник пишет: «Опять не включается монитор у бухгалтера, заявка на это вроде была». Если незакрытая заявка "
         "по этой проблеме уже есть, добавь к ней комментарий «Повторное обращение»; иначе создай новую заявку со "
         "средним приоритетом в категории «Оборудование».",
         {"type": "object", "required": ["action", "ticket_id", "message"],
          "properties": {"action": {"type": "string", "enum": ["created", "updated"]}, "ticket_id": RID, "message": MSG}},
         '{"action": "created|updated", "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "add_comment"],
         expected=[("create_ticket", lambda a, c: "монитор" in str(a.get("description", "")).lower()
                    and a.get("priority") == "средний" and a.get("category") == "Оборудование" and not c.created_ids)],
         answer_ok=lambda a, c: g(a, "action") == "created" and g(a, "ticket_id") in c.created_ids,
         state_ok=lambda tk, c: len(created(tk, c)) == 1 and only(tk, c, [], 1)),
    Task("T8c", "E4", "Выбор между комментарием и созданием (комментарий)",
         "Пользователь сообщает, что снова не открывается корпоративный портал. Если заявка по этой проблеме уже есть и "
         "не закрыта, добавь в неё комментарий «Проблема повторилась»; иначе создай новую заявку с высоким приоритетом "
         "в категории «Сеть».",
         {"type": "object", "required": ["action", "ticket_id", "message"],
          "properties": {"action": {"type": "string", "enum": ["created", "updated"]}, "ticket_id": RID, "message": MSG}},
         '{"action": "created|updated", "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "add_comment"],
         expected=[("add_comment", lambda a, c: a.get("ticket_id") == "REQ-109"
                    and "повторилась" in str(a.get("text", "")).lower())],
         answer_ok=lambda a, c: g(a, "action") == "updated" and g(a, "ticket_id") == "REQ-109",
         state_ok=lambda tk, c: comment_has(tk["REQ-109"], "повторилась") and only(tk, c, ["REQ-109"])),

    Task("T9b", "E5", "Создание заявки с типизированными полями",
         "Создай заявку: описание «Заменить картридж в принтере отдела кадров», приоритет — низкий, категория — "
         "«Оборудование», выполнить до 3 ноября 2026 года, оценка трудозатрат — 2 часа.",
         {"type": "object", "required": ["success", "ticket_id", "message"],
          "properties": {"success": {"type": "boolean"}, "ticket_id": {**RID, "nullable": True}, "message": MSG}},
         '{"success": true|false, "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "update_ticket"],
         expected=[("create_ticket", lambda a, c: "картридж" in str(a.get("description", "")).lower()
                    and a.get("priority") == "низкий" and a.get("category") == "Оборудование"
                    and a.get("due_date") == "2026-11-03" and a.get("estimated_hours") == 2 and not c.created_ids),
                   ("update_ticket", lambda a, c: a.get("ticket_id") in c.created_ids)],
         answer_ok=lambda a, c: g(a, "success") is True and g(a, "ticket_id") in c.created_ids,
         state_ok=lambda tk, c: len(created(tk, c)) == 1 and created(tk, c)[0]["due_date"] == "2026-11-03"
         and created(tk, c)[0]["estimated_hours"] == 2 and created(tk, c)[0]["priority"] == "низкий"
         and only(tk, c, [], 1)),
    Task("T9c", "E5", "Регистрация заявки с типизированными полями",
         "Зарегистрируй заявку «Подключить нового сотрудника к VPN»: приоритет средний, категория «Доступ», срок "
         "20.10.2026, оценка трудозатрат — 3 ч.",
         {"type": "object", "required": ["success", "ticket_id", "message"],
          "properties": {"success": {"type": "boolean"}, "ticket_id": {**RID, "nullable": True}, "message": MSG}},
         '{"success": true|false, "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "update_ticket"],
         expected=[("create_ticket", lambda a, c: "vpn" in str(a.get("description", "")).lower()
                    and a.get("priority") == "средний" and a.get("category") == "Доступ"
                    and a.get("due_date") == "2026-10-20" and a.get("estimated_hours") == 3 and not c.created_ids),
                   ("update_ticket", lambda a, c: a.get("ticket_id") in c.created_ids)],
         answer_ok=lambda a, c: g(a, "success") is True and g(a, "ticket_id") in c.created_ids,
         state_ok=lambda tk, c: len(created(tk, c)) == 1 and created(tk, c)[0]["due_date"] == "2026-10-20"
         and created(tk, c)[0]["estimated_hours"] == 3 and created(tk, c)[0]["category"] == "Доступ"
         and only(tk, c, [], 1)),
    Task("T10b", "E5", "Изменение статуса по номеру заявки", "Возьми заявку № 106 в работу.",
         SUCCESS_SCHEMA, '{"success": true|false, "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "change_status"],
         expected=[("change_status", lambda a, c: a.get("ticket_id") == "REQ-106" and a.get("new_status") == "В работе")],
         answer_ok=lambda a, c: g(a, "success") is True,
         state_ok=lambda tk, c: tk["REQ-106"]["status"] == "В работе" and only(tk, c, ["REQ-106"])),
    Task("T10c", "E5", "Изменение статуса по номеру заявки", "Отправь заявку 103 на проверку.",
         SUCCESS_SCHEMA, '{"success": true|false, "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "change_status"],
         expected=[("change_status", lambda a, c: a.get("ticket_id") == "REQ-103" and a.get("new_status") == "На проверке")],
         answer_ok=lambda a, c: g(a, "success") is True,
         state_ok=lambda tk, c: tk["REQ-103"]["status"] == "На проверке" and only(tk, c, ["REQ-103"])),

    fault_task("T11b", "Добавь к заявке REQ-112 комментарий «Ожидаем оборудование» и сообщи результат.",
               "add_comment", lambda a, c: a.get("ticket_id") == "REQ-112"
               and "ожидаем оборудование" in str(a.get("text", "")).lower(),
               lambda tk, c: comment_has(tk["REQ-112"], "ожидаем оборудование") and only(tk, c, ["REQ-112"]),
               "unavailable"),
    fault_task("T11c", "Повысь приоритет заявки REQ-113 до среднего и сообщи результат.",
               "update_ticket", lambda a, c: a.get("ticket_id") == "REQ-113" and a.get("priority") == "средний"
               and all(a.get(k) is None for k in ("description", "category", "due_date", "estimated_hours")),
               lambda tk, c: tk["REQ-113"]["priority"] == "средний" and only(tk, c, ["REQ-113"]), "unavailable"),
    fault_task("T12b", "Назначь исполнителем заявки REQ-112 сотрудника Сидоров и сообщи, выполнена ли операция и кто "
                       "сейчас исполнитель заявки.",
               "assign_ticket", lambda a, c: a.get("ticket_id") == "REQ-112" and a.get("assignee") == "Сидоров",
               lambda tk, c: only(tk, c, ["REQ-112"]) or only(tk, c), "incomplete",
               schema={"type": "object", "required": ["success", "current", "message"],
                       "properties": {"success": {"type": "boolean"}, "current": EMP_N, "message": MSG}},
               example='{"success": true|false, "current": "<фамилия исполнителя или null>", "message": "..."}',
               answer_ok=t12_variant("assignee", "Сидоров")),
    fault_task("T12c", "Переведи заявку REQ-107 в статус «В работе» и сообщи, выполнена ли операция и какой статус у "
                       "заявки сейчас.",
               "change_status", lambda a, c: a.get("ticket_id") == "REQ-107" and a.get("new_status") == "В работе",
               lambda tk, c: only(tk, c, ["REQ-107"]) or only(tk, c), "incomplete",
               schema={"type": "object", "required": ["success", "current", "message"],
                       "properties": {"success": {"type": "boolean"}, "current": STA, "message": MSG}},
               example='{"success": true|false, "current": "<текущий статус>", "message": "..."}',
               answer_ok=t12_variant("status", "В работе")),
]
