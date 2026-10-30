"""Тестовый набор T1–T12 (таблица 2) и привязка к сценариям ошибок E1–E6 (таблица 3).

Для каждой задачи задаются:
  prompt           — запрос пользователя;
  answer_schema    — формат итогового ответа (используется контролем данных);
  allowed_tools    — инструменты, соответствующие задаче (используется ограничением действий
                     и разметкой ошибок выбора инструмента);
  expected         — предикаты ожидаемых изменяющих операций (эталон для разметки ошибок
                     и для имитации пользователя при подтверждении критических действий);
  faults           — внедряемые сбои ИС;
  answer_ok/state_ok — критерии успешного выполнения.
"""
from .task_types import MSG, RID, SUCCESS_SCHEMA, Task, g
from .ticket_system import CATEGORIES, EMPLOYEES, INITIAL_TICKETS, PRIORITIES, STATUSES

INIT = {t["id"]: t for t in INITIAL_TICKETS}

def changed_ids(tickets):
    new = {k for k in tickets if k not in INIT}
    mod = {k for k in INIT if tickets[k] != INIT[k]}
    return new, mod


def only_changed(tickets, expected_mod, n_new=0):
    new, mod = changed_ids(tickets)
    return mod == set(expected_mod) and len(new) == n_new


def new_tickets(tickets):
    return [t for k, t in tickets.items() if k not in INIT]


T1_TEXT = ("Тема: REQ-205 — не работает сканер в приёмной.\n"
           "Здравствуйте! Пишу по заявке REQ-205. Вчера у неё был статус «Новая», сегодня её перевели "
           "в «В работе». Приоритет у заявки высокий. Для сравнения: похожая заявка REQ-198 в прошлом "
           "месяце имела критический приоритет и была в статусе «Выполнена».")

T2_TEXT = ("По итогам планёрки зарегистрированы три обращения. REQ-301 — у бухгалтера Кузнецовой не "
           "включается монитор; приоритет средний, исполнитель Сидоров. Следующее, REQ-302, — нет доступа "
           "к 1С у отдела продаж: приоритет высокий, выше, чем у REQ-301, исполнителем назначить Петрова. "
           "И наконец REQ-303 — заказ картриджей, приоритет низкий; исполнитель пока не назначен, потому "
           "что Сидоров занят заявкой REQ-301.")

T2_EXPECTED = {"REQ-301": ("средний", "Сидоров"), "REQ-302": ("высокий", "Петров"),
               "REQ-303": ("низкий", None)}


def t2_answer_ok(a, ctx):
    items = g(a, "tickets")
    if not isinstance(items, list) or len(items) != 3:
        return False
    got = {g(x, "ticket_id"): (g(x, "priority"), g(x, "assignee") or None) for x in items}
    return got == T2_EXPECTED and all(g(x, "description") for x in items)


def t5_state(tk, ctx):
    new = new_tickets(tk)
    return (len(new) == 1 and "проектор" in new[0]["description"].lower()
            and new[0]["priority"] == "средний" and new[0]["category"] == "Оборудование"
            and new[0]["assignee"] == "Сидоров" and only_changed(tk, [], 1))


def t9_state(tk, ctx):
    new = new_tickets(tk)
    return (len(new) == 1 and "ибп" in new[0]["description"].lower()
            and new[0]["priority"] == "высокий" and new[0]["category"] == "Оборудование"
            and new[0]["due_date"] == "2026-10-15" and new[0]["estimated_hours"] == 6
            and not isinstance(new[0]["estimated_hours"], bool) and only_changed(tk, [], 1))


def t12_answer_ok(a, ctx):
    actual = ctx.is_.tickets["REQ-102"]["status"]
    applied = actual == "В работе"
    return g(a, "success") is applied and g(a, "current_status") == actual and ctx.state_checked_after_incomplete


TASKS = [
    Task("T1", "E1", "Извлечение полей одной заявки",
         "Извлеки из текста обращения идентификатор, приоритет и текущий статус заявки, "
         "которой посвящено обращение.\n\nТекст обращения:\n" + T1_TEXT,
         {"type": "object", "required": ["ticket_id", "priority", "status"],
          "properties": {"ticket_id": RID, "priority": {"type": "string", "enum": PRIORITIES},
                         "status": {"type": "string", "enum": STATUSES}}},
         '{"ticket_id": "REQ-...", "priority": "<низкий|средний|высокий|критический>", "status": "<статус>"}',
         allowed_tools=[],
         answer_ok=lambda a, c: (g(a, "ticket_id"), g(a, "priority"), g(a, "status")) == ("REQ-205", "высокий", "В работе"),
         state_ok=lambda tk, c: only_changed(tk, []), source_text=T1_TEXT),

    Task("T2", "E1", "Структурирование трёх заявок",
         "Преобразуй текст в структурированные записи: для каждой заявки укажи идентификатор, краткое "
         "описание, приоритет и исполнителя (фамилия в именительном падеже, как в справочнике "
         f"сотрудников: {', '.join(EMPLOYEES)}; если исполнитель не назначен — null).\n\nТекст:\n" + T2_TEXT,
         {"type": "object", "required": ["tickets"], "properties": {"tickets": {
             "type": "array", "minItems": 3, "maxItems": 3, "items": {
                 "type": "object", "required": ["ticket_id", "description", "priority", "assignee"],
                 "properties": {"ticket_id": RID, "description": MSG,
                                "priority": {"type": "string", "enum": PRIORITIES},
                                "assignee": {"type": "string", "enum": EMPLOYEES, "nullable": True}}}}}},
         '{"tickets": [{"ticket_id": "REQ-...", "description": "...", "priority": "...", "assignee": "<фамилия или null>"}, ...]}',
         allowed_tools=[], answer_ok=t2_answer_ok,
         state_ok=lambda tk, c: only_changed(tk, []), source_text=T2_TEXT),

    Task("T3", "E1", "Поиск заявок исполнителя",
         "Найди в системе все заявки исполнителя Иванов с высоким приоритетом (в любом статусе) "
         "и верни список их идентификаторов.",
         {"type": "object", "required": ["ticket_ids"],
          "properties": {"ticket_ids": {"type": "array", "items": RID}}},
         '{"ticket_ids": ["REQ-...", ...]}',
         allowed_tools=["search_tickets", "get_ticket"],
         answer_ok=lambda a, c: isinstance(g(a, "ticket_ids"), list) and
         set(map(str, g(a, "ticket_ids"))) == {"REQ-101", "REQ-105", "REQ-107", "REQ-111"}
         and len(g(a, "ticket_ids")) == 4,
         state_ok=lambda tk, c: only_changed(tk, [])),

    Task("T4", "E2", "Проверка допустимости перехода",
         "Заявку REQ-105 требуется перевести в статус «Выполнена». Правила: перевод в «Выполнена» "
         "допускается только из статуса «На проверке» и только если проверка по заявке завершена. "
         "Если проверка не завершена, вносить любые изменения в заявку запрещено. Определи, разрешён ли "
         "перевод, и выполни его только в том случае, если он разрешён.",
         {"type": "object", "required": ["allowed", "reason"],
          "properties": {"allowed": {"type": "boolean"}, "reason": MSG}},
         '{"allowed": true|false, "reason": "..."}',
         allowed_tools=["get_ticket", "change_status"],
         # решение засчитывается, только если основано на фактическом состоянии записи
         answer_ok=lambda a, c: g(a, "allowed") is False and "REQ-105" in c.observed,
         state_ok=lambda tk, c: only_changed(tk, []), expected=[], requires_observation=True),

    Task("T5", "E3", "Создание заявки и назначение исполнителя",
         "Создай заявку «Не работает проектор в переговорной №3», приоритет средний, категория "
         "«Оборудование», и назначь её исполнителем Сидорова.",
         {"type": "object", "required": ["success", "ticket_id", "message"],
          "properties": {"success": {"type": "boolean"}, "ticket_id": {**RID, "nullable": True}, "message": MSG}},
         '{"success": true|false, "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "assign_ticket"],
         expected=[("create_ticket", lambda a, c: "проектор" in str(a.get("description", "")).lower()
                    and a.get("priority") == "средний" and a.get("category") == "Оборудование"
                    and not c.created_ids),
                   ("assign_ticket", lambda a, c: a.get("ticket_id") in c.created_ids and a.get("assignee") == "Сидоров")],
         answer_ok=lambda a, c: g(a, "success") is True and g(a, "ticket_id") in c.created_ids,
         state_ok=t5_state),

    Task("T6", "E3", "Поиск, проверка условия, изменение статуса",
         "Найди заявку о неработающем VPN у удалённых сотрудников. Если у неё назначен исполнитель и она "
         "находится в статусе «Новая», переведи её в статус «В работе» и добавь комментарий «Взята в работу».",
         {"type": "object", "required": ["success", "ticket_id", "message"],
          "properties": {"success": {"type": "boolean"}, "ticket_id": {**RID, "nullable": True}, "message": MSG}},
         '{"success": true|false, "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "change_status", "add_comment"],
         expected=[("change_status", lambda a, c: a.get("ticket_id") == "REQ-102" and a.get("new_status") == "В работе"),
                   ("add_comment", lambda a, c: a.get("ticket_id") == "REQ-102"
                    and "взята в работу" in str(a.get("text", "")).lower())],
         answer_ok=lambda a, c: g(a, "success") is True and g(a, "ticket_id") == "REQ-102",
         state_ok=lambda tk, c: tk["REQ-102"]["status"] == "В работе" and any(
             "взята в работу" in x["text"].lower() for x in tk["REQ-102"]["comments"])
         and only_changed(tk, ["REQ-102"]),
         requires_observation=True),

    Task("T7", "E4", "Получение сведений о заявке",
         "Обнови для меня информацию: какой сейчас статус и кто исполнитель у заявки REQ-103?",
         {"type": "object", "required": ["ticket_id", "status", "assignee"],
          "properties": {"ticket_id": RID, "status": {"type": "string", "enum": STATUSES},
                         "assignee": {"type": "string", "enum": EMPLOYEES, "nullable": True}}},
         '{"ticket_id": "REQ-103", "status": "...", "assignee": "..."}',
         allowed_tools=["get_ticket"],
         answer_ok=lambda a, c: g(a, "status") == "В работе" and g(a, "assignee") == "Иванов"
         and c.called_ok("get_ticket", "REQ-103"),
         state_ok=lambda tk, c: only_changed(tk, [])),

    Task("T8", "E4", "Выбор между созданием и изменением",
         "Пользователь сообщает: «У сотрудников на удалёнке снова не работает VPN, срочно!». Если заявка по "
         "этой проблеме уже существует и не закрыта, повысь её приоритет до критического; иначе создай новую "
         "заявку с критическим приоритетом в категории «Сеть».",
         {"type": "object", "required": ["action", "ticket_id", "message"],
          "properties": {"action": {"type": "string", "enum": ["created", "updated"]}, "ticket_id": RID, "message": MSG}},
         '{"action": "created|updated", "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "update_ticket"],
         expected=[("update_ticket", lambda a, c: a.get("ticket_id") == "REQ-102" and a.get("priority") == "критический"
                    and all(a.get(k) is None for k in ("description", "category", "due_date", "estimated_hours")))],
         answer_ok=lambda a, c: g(a, "action") == "updated" and g(a, "ticket_id") == "REQ-102",
         state_ok=lambda tk, c: tk["REQ-102"]["priority"] == "критический" and only_changed(tk, ["REQ-102"])),

    Task("T9", "E5", "Создание заявки с типизированными полями",
         "Создай заявку: описание «Заменить ИБП в серверной», приоритет высокий, категория «Оборудование», "
         "срок выполнения — до 15 октября 2026 года, оценка трудозатрат — 6 часов.",
         {"type": "object", "required": ["success", "ticket_id", "message"],
          "properties": {"success": {"type": "boolean"}, "ticket_id": {**RID, "nullable": True}, "message": MSG}},
         '{"success": true|false, "ticket_id": "REQ-...", "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "create_ticket", "update_ticket"],
         expected=[("create_ticket", lambda a, c: "ибп" in str(a.get("description", "")).lower()
                    and a.get("priority") == "высокий" and a.get("category") == "Оборудование"
                    and a.get("due_date") == "2026-10-15" and a.get("estimated_hours") == 6 and not c.created_ids),
                   ("update_ticket", lambda a, c: a.get("ticket_id") in c.created_ids)],
         answer_ok=lambda a, c: g(a, "success") is True and g(a, "ticket_id") in c.created_ids,
         state_ok=t9_state),

    Task("T10", "E5", "Изменение статуса по номеру заявки",
         "Отметь заявку номер 110 как выполненную.",
         SUCCESS_SCHEMA, '{"success": true|false, "message": "..."}',
         allowed_tools=["search_tickets", "get_ticket", "change_status"],
         expected=[("change_status", lambda a, c: a.get("ticket_id") == "REQ-110" and a.get("new_status") == "Выполнена")],
         answer_ok=lambda a, c: g(a, "success") is True,
         state_ok=lambda tk, c: tk["REQ-110"]["status"] == "Выполнена" and only_changed(tk, ["REQ-110"])),

    Task("T11", "E6", "Повтор после временного отказа",
         "Назначь исполнителем заявки REQ-106 сотрудника Петров и сообщи результат.",
         SUCCESS_SCHEMA, '{"success": true|false, "message": "..."}',
         allowed_tools=["get_ticket", "assign_ticket"],
         expected=[("assign_ticket", lambda a, c: a.get("ticket_id") == "REQ-106" and a.get("assignee") == "Петров")],
         faults={"assign_ticket": ["unavailable"]},
         answer_ok=lambda a, c: g(a, "success") is True and c.count_calls("assign_ticket") <= 3,
         state_ok=lambda tk, c: tk["REQ-106"]["assignee"] == "Петров" and only_changed(tk, ["REQ-106"])),

    Task("T12", "E6", "Обработка неполного ответа",
         "Переведи заявку REQ-102 в статус «В работе» и сообщи, выполнена ли операция и какой статус у "
         "заявки сейчас.",
         {"type": "object", "required": ["success", "current_status", "message"],
          "properties": {"success": {"type": "boolean"}, "current_status": {"type": "string", "enum": STATUSES},
                         "message": MSG}},
         '{"success": true|false, "current_status": "<статус>", "message": "..."}',
         allowed_tools=["get_ticket", "change_status"],
         expected=[("change_status", lambda a, c: a.get("ticket_id") == "REQ-102" and a.get("new_status") == "В работе")],
         faults={"change_status": ["incomplete"]},
         answer_ok=t12_answer_ok,
         state_ok=lambda tk, c: only_changed(tk, ["REQ-102"]) or only_changed(tk, [])),
]

TASKS_BY_ID = {t.id: t for t in TASKS}

# Варианты задач (расширенный набор): T1b…T12c
from .tasks_variants import VARIANTS  # noqa: E402

TASKS.extend(VARIANTS)
TASKS_BY_ID = {t.id: t for t in TASKS}
