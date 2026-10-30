"""Имитационная информационная система управления заявками.

Система намеренно реализует «мягкую» серверную валидацию, как многие реальные
учётные системы: проверяется существование записи и граф переходов статусов,
но не форматы дат, типы чисел или справочник сотрудников. Поэтому некорректные
параметры (E5) могут быть приняты и тихо испортить данные — именно это
позволяет оценить методы контроля на стороне агента.
"""
import copy
import re

STATUSES = ["Новая", "В работе", "На проверке", "Выполнена", "Отменена"]
PRIORITIES = ["низкий", "средний", "высокий", "критический"]
CATEGORIES = ["Оборудование", "Программное обеспечение", "Сеть", "Доступ", "Прочее"]
EMPLOYEES = ["Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецова"]

# Граф допустимых переходов статусов (проверяется самой ИС).
TRANSITIONS = {
    "Новая": {"В работе", "Отменена"},
    "В работе": {"На проверке", "Отменена"},
    "На проверке": {"Выполнена", "В работе"},
    "Выполнена": set(),
    "Отменена": set(),
}

ID_RE = re.compile(r"^REQ-\d+$")
PAGE_SIZE = 5


def _t(id_, description, priority, status, assignee, category,
       review="не требуется", comments=None, history=None):
    return {
        "id": id_, "description": description, "priority": priority,
        "status": status, "assignee": assignee, "category": category,
        "review_status": review, "due_date": None, "estimated_hours": None,
        "comments": comments or [], "history": history or [],
    }


INITIAL_TICKETS = [
    _t("REQ-101", "Не работает принтер в бухгалтерии", "высокий", "В работе", "Иванов", "Оборудование"),
    _t("REQ-102", "Не работает VPN у удалённых сотрудников", "высокий", "Новая", "Петров", "Сеть"),
    _t("REQ-103", "Установить ПО для отдела кадров", "средний", "В работе", "Иванов",
       "Программное обеспечение",
       history=[
           {"date": "2026-09-20", "event": "Создана", "status": "Новая", "assignee": "Петров"},
           {"date": "2026-09-22", "event": "Статус изменён", "status": "В работе"},
           {"date": "2026-09-23", "event": "Исполнитель изменён", "assignee": "Иванов"},
       ]),
    _t("REQ-104", "Замена картриджа в приёмной", "низкий", "Выполнена", "Сидоров", "Оборудование"),
    _t("REQ-105", "Ошибка доступа к CRM у отдела продаж", "высокий", "На проверке", "Иванов", "Доступ",
       review="в процессе",
       comments=[{"author": "Смирнов",
                  "text": "Исправление внесено, проверка почти завершена — думаю, можно закрывать."}]),
    _t("REQ-106", "Настройка почты для нового сотрудника", "средний", "Новая", None,
       "Программное обеспечение"),
    _t("REQ-107", "Медленная работа сервера 1С", "высокий", "Новая", "Иванов", "Программное обеспечение"),
    _t("REQ-108", "Обновить антивирусные базы", "высокий", "Выполнена", "Петров", "Программное обеспечение"),
    _t("REQ-109", "Не открывается корпоративный портал", "критический", "В работе", "Иванов", "Сеть"),
    _t("REQ-110", "Подготовить отчёт по инцидентам за квартал", "высокий", "На проверке", "Смирнов",
       "Прочее", review="завершена"),
    _t("REQ-111", "Перенос рабочего места бухгалтера", "высокий", "Отменена", "Иванов", "Оборудование"),
    _t("REQ-112", "Настройка VPN-шлюза для нового офиса", "средний", "Новая", None, "Сеть"),
    _t("REQ-113", "Заменить клавиатуру", "низкий", "Новая", "Иванов", "Оборудование"),
]


def brief(t):
    return {k: t[k] for k in ("id", "description", "priority", "status", "assignee")}


class TicketSystem:
    """Состояние ИС + программный интерфейс. faults: {tool: [тип сбоя, ...]} —
    сбои срабатывают на первых вызовах соответствующего инструмента."""

    def __init__(self, faults=None, extra=None):
        self.tickets = {t["id"]: copy.deepcopy(t) for t in INITIAL_TICKETS}
        for t in extra or []:          # собственные записи задачи (варианты тестового набора)
            self.tickets[t["id"]] = copy.deepcopy(t)
        self.faults = {k: list(v) for k, v in (faults or {}).items()}
        self._next_id = 500
        self.call_log = []  # (tool, args, result)

    def snapshot(self):
        return copy.deepcopy(self.tickets)

    def call(self, name, args):
        op = getattr(self, "op_" + name, None)
        if op is None:
            result = {"error": "UNKNOWN_TOOL", "message": f"Операция {name} не поддерживается"}
        else:
            queue = self.faults.get(name)
            fault = queue.pop(0) if queue else None
            if fault == "unavailable":
                result = {"error": "SERVICE_UNAVAILABLE", "code": 503}
            elif fault == "incomplete":
                # Ответ оборван, операция фактически НЕ применена.
                result = {"request_id": "c7f3a1", "result": None}
            else:
                try:
                    result = op(**args)
                except TypeError as e:
                    result = {"error": "BAD_REQUEST", "message": str(e)}
        self.call_log.append((name, copy.deepcopy(args), copy.deepcopy(result)))
        return result

    def _get(self, ticket_id):
        if not isinstance(ticket_id, str) or ticket_id not in self.tickets:
            return None
        return self.tickets[ticket_id]

    @staticmethod
    def _nf(ticket_id):
        return {"error": "NOT_FOUND", "message": f"Заявка {ticket_id} не найдена"}

    def op_search_tickets(self, assignee=None, priority=None, status=None, text=None, page=1):
        items = [t for t in self.tickets.values()
                 if (assignee is None or t["assignee"] == assignee)
                 and (priority is None or t["priority"] == priority)
                 and (status is None or t["status"] == status)
                 and (text is None or str(text).lower() in t["description"].lower())]
        items.sort(key=lambda t: t["id"])
        try:
            page = max(1, int(page))
        except (TypeError, ValueError):
            page = 1
        chunk = items[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        return {"items": [brief(t) for t in chunk], "page": page, "total": len(items),
                "has_more": page * PAGE_SIZE < len(items)}

    def op_get_ticket(self, ticket_id):
        t = self._get(ticket_id)
        if t is None:
            return self._nf(ticket_id)
        return {k: v for k, v in t.items() if k != "history"}

    def op_get_ticket_history(self, ticket_id):
        t = self._get(ticket_id)
        return self._nf(ticket_id) if t is None else {"ticket_id": ticket_id, "history": t["history"]}

    def op_create_ticket(self, description, priority, category, due_date=None, estimated_hours=None):
        self._next_id += 1
        tid = f"REQ-{self._next_id}"
        self.tickets[tid] = _t(tid, description, priority, "Новая", None, category)
        self.tickets[tid]["due_date"] = due_date
        self.tickets[tid]["estimated_hours"] = estimated_hours
        return {"id": tid, "created": True}

    def op_update_ticket(self, ticket_id, description=None, priority=None, category=None,
                         due_date=None, estimated_hours=None):
        t = self._get(ticket_id)
        if t is None:
            return self._nf(ticket_id)
        changed = {}
        for k, v in (("description", description), ("priority", priority), ("category", category),
                     ("due_date", due_date), ("estimated_hours", estimated_hours)):
            if v is not None:
                t[k] = v
                changed[k] = v
        return {"ticket_id": ticket_id, "updated": changed}

    def op_assign_ticket(self, ticket_id, assignee):
        t = self._get(ticket_id)
        if t is None:
            return self._nf(ticket_id)
        t["assignee"] = assignee
        return {"ticket_id": ticket_id, "assignee": assignee}

    def op_change_status(self, ticket_id, new_status):
        t = self._get(ticket_id)
        if t is None:
            return self._nf(ticket_id)
        if new_status not in STATUSES:
            return {"error": "INVALID_STATUS", "message": f"Недопустимый статус: {new_status}"}
        if new_status not in TRANSITIONS[t["status"]]:
            return {"error": "TRANSITION_NOT_ALLOWED",
                    "message": f"Переход {t['status']} → {new_status} недопустим"}
        t["status"] = new_status
        return {"ticket_id": ticket_id, "status": new_status}

    def op_add_comment(self, ticket_id, text):
        t = self._get(ticket_id)
        if t is None:
            return self._nf(ticket_id)
        t["comments"].append({"author": "agent", "text": text})
        return {"ticket_id": ticket_id, "comment_added": True}
