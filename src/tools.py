"""Описание инструментов агента, строгая схемная валидация и детерминированные функции."""
import re

from .ticket_system import CATEGORIES, EMPLOYEES, ID_RE, PRIORITIES, STATUSES, TRANSITIONS

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

S = {"type": "string"}
TID = {"type": "string", "pattern": ID_RE.pattern, "description": "Идентификатор заявки, например REQ-101"}
EMP = {"type": "string", "enum": EMPLOYEES, "description": "Фамилия сотрудника"}

# name -> описание, параметры (JSON Schema), обязательные, признак изменения данных
TOOL_SPECS = {
    "search_tickets": {
        "description": "Поиск заявок по фильтрам. Результаты выдаются постранично (по 5 записей).",
        "params": {
            "assignee": EMP,
            "priority": {"type": "string", "enum": PRIORITIES},
            "status": {"type": "string", "enum": STATUSES},
            "text": {"type": "string", "description": "Фрагмент описания заявки"},
            "page": {"type": "integer", "description": "Номер страницы, начиная с 1"},
        },
        "required": [], "mutating": False,
    },
    "get_ticket": {
        "description": "Получить полные сведения о заявке по идентификатору.",
        "params": {"ticket_id": TID}, "required": ["ticket_id"], "mutating": False,
    },
    "get_ticket_history": {
        "description": "Получить журнал изменений заявки по идентификатору.",
        "params": {"ticket_id": TID}, "required": ["ticket_id"], "mutating": False,
    },
    "create_ticket": {
        "description": "Создать новую заявку. Исполнитель назначается отдельной операцией assign_ticket.",
        "params": {
            "description": S,
            "priority": {"type": "string", "enum": PRIORITIES},
            "category": {"type": "string", "enum": CATEGORIES},
            "due_date": {"type": "string", "pattern": DATE_RE.pattern, "description": "Срок, формат YYYY-MM-DD"},
            "estimated_hours": {"type": "integer", "description": "Оценка трудозатрат, часов"},
        },
        "required": ["description", "priority", "category"], "mutating": True,
    },
    "update_ticket": {
        "description": "Обновить поля заявки по идентификатору (описание, приоритет, категорию, срок, трудозатраты).",
        "params": {
            "ticket_id": TID, "description": S,
            "priority": {"type": "string", "enum": PRIORITIES},
            "category": {"type": "string", "enum": CATEGORIES},
            "due_date": {"type": "string", "pattern": DATE_RE.pattern},
            "estimated_hours": {"type": "integer"},
        },
        "required": ["ticket_id"], "mutating": True,
    },
    "assign_ticket": {
        "description": "Назначить исполнителя заявки.",
        "params": {"ticket_id": TID, "assignee": EMP},
        "required": ["ticket_id", "assignee"], "mutating": True,
    },
    "change_status": {
        "description": "Изменить статус заявки.",
        "params": {"ticket_id": TID, "new_status": {"type": "string", "enum": STATUSES}},
        "required": ["ticket_id", "new_status"], "mutating": True,
    },
    "add_comment": {
        "description": "Добавить комментарий к заявке.",
        "params": {"ticket_id": TID, "text": S},
        "required": ["ticket_id", "text"], "mutating": True,
    },
}

# Инструмент, добавляемый конфигурацией «Детерминированные функции».
DETERMINISTIC_TOOL_SPECS = {
    "check_status_transition": {
        "description": "Детерминированная проверка по регламенту: разрешён ли перевод заявки в указанный статус.",
        "params": {"ticket_id": TID, "new_status": {"type": "string", "enum": STATUSES}},
        "required": ["ticket_id", "new_status"], "mutating": False,
    },
}

ALL_SPECS = {**TOOL_SPECS, **DETERMINISTIC_TOOL_SPECS}
MUTATING = {n for n, s in TOOL_SPECS.items() if s["mutating"]}
CRITICAL = {"create_ticket", "update_ticket", "assign_ticket", "change_status"}


def to_ollama(names):
    out = []
    for n in names:
        spec = ALL_SPECS[n]
        props = {k: {kk: vv for kk, vv in v.items() if kk != "pattern"} for k, v in spec["params"].items()}
        out.append({"type": "function", "function": {
            "name": n, "description": spec["description"],
            "parameters": {"type": "object", "properties": props, "required": spec["required"]}}})
    return out

def check_value(schema, value, path):
    """Проверка значения по упрощённой JSON-схеме. Возвращает список проблем."""
    if value is None:
        return [] if schema.get("nullable") else [f"{path}: значение отсутствует"]
    t = schema.get("type")
    type_ok = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }.get(t, True)
    if not type_ok:
        return [f"{path}: ожидается тип {t}, получено {value!r}"]
    problems = []
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: значение {value!r} не входит в допустимые {schema['enum']}")
    if "pattern" in schema and isinstance(value, str) and not re.match(schema["pattern"], value):
        problems.append(f"{path}: значение {value!r} не соответствует формату {schema['pattern']}")
    if t == "array":
        n = len(value)
        if "minItems" in schema and n < schema["minItems"] or "maxItems" in schema and n > schema["maxItems"]:
            problems.append(f"{path}: неверное число элементов ({n})")
        for i, item in enumerate(value):
            problems += check_value(schema.get("items", {}), item, f"{path}[{i}]")
    if t == "object":
        for k in schema.get("required", []):
            if k not in value:
                problems.append(f"{path}.{k}: обязательное поле отсутствует")
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                problems += check_value(sub, value[k], f"{path}.{k}")
    return problems


def validate_args(name, args):
    spec = ALL_SPECS.get(name)
    if spec is None:
        return [f"неизвестный инструмент {name}"]
    problems = [f"{k}: обязательный параметр отсутствует" for k in spec["required"] if args.get(k) is None]
    for k, v in args.items():
        if k not in spec["params"]:
            problems.append(f"{k}: неизвестный параметр")
        elif v is not None:
            problems += check_value(spec["params"][k], v, k)
    return problems

MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7,
          "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
PRIORITY_SYN = {"низк": "низкий", "средн": "средний", "высок": "высокий", "критич": "критический"}
STATUS_SYN = {"нов": "Новая", "в работ": "В работе", "на провер": "На проверке",
              "выполн": "Выполнена", "отмен": "Отменена"}


def norm_ticket_id(v):
    if isinstance(v, int):
        return f"REQ-{v}"
    if isinstance(v, str):
        m = re.search(r"(\d+)", v)
        if m and (ID_RE.match(v.strip().upper()) or re.fullmatch(r"\s*(№|N|#)?\s*\d+\s*", v)):
            return f"REQ-{m.group(1)}"
    return v


def _by_prefix(v, table):
    if not isinstance(v, str):
        return v
    low = v.strip().lower()
    for pref, canon in table.items():
        if low.startswith(pref):
            return canon
    return v


def norm_employee(v):
    if not isinstance(v, str):
        return v
    v = v.strip()
    if v.lower() in ("", "null", "none", "нет", "не назначен", "-", "—"):
        return None
    if v in EMPLOYEES:
        return v
    low = v.lower()
    for e in EMPLOYEES:  # приведение падежной формы («Петрова», «Сидорову») к справочнику
        stem = e.lower().rstrip("а")
        if low.startswith(stem) and len(low) - len(stem) <= 3:
            return e
    return v


def norm_date(v):
    if not isinstance(v, str) or DATE_RE.match(v):
        return v
    m = re.fullmatch(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*", v)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", v.lower())
    if m:
        for pref, num in sorted(MONTHS.items(), key=lambda x: -len(x[0])):
            if m.group(2).startswith(pref):
                return f"{m.group(3)}-{num:02d}-{int(m.group(1)):02d}"
    return v


def norm_int(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(\d+)\s*([а-я.]*)\s*", v)
        if m:
            return int(m.group(1))
    return v


FIELD_NORMALIZERS = {
    "ticket_id": norm_ticket_id, "priority": lambda v: _by_prefix(v, PRIORITY_SYN),
    "status": lambda v: _by_prefix(v, STATUS_SYN), "new_status": lambda v: _by_prefix(v, STATUS_SYN),
    "current_status": lambda v: _by_prefix(v, STATUS_SYN),
    "assignee": norm_employee, "due_date": norm_date, "estimated_hours": norm_int,
}


def normalize(obj):
    """Рекурсивно приводит известные поля к каноническому формату."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in FIELD_NORMALIZERS and not isinstance(v, (dict, list)):
                out[k] = FIELD_NORMALIZERS[k](v)
            elif k == "ticket_ids" and isinstance(v, list):
                out[k] = [norm_ticket_id(x) for x in v]
            else:
                out[k] = normalize(v)
        return out
    if isinstance(obj, list):
        return [normalize(x) for x in obj]
    return obj

def transition_rule(ticket, new_status):
    """Регламент: граф переходов ИС + перевод в «Выполнена» только после завершённой проверки."""
    if new_status not in TRANSITIONS.get(ticket["status"], set()):
        return False, f"Переход {ticket['status']} → {new_status} не предусмотрен"
    if new_status == "Выполнена" and ticket["review_status"] not in ("завершена", "не требуется"):
        return False, f"Проверка заявки не завершена (review_status = {ticket['review_status']})"
    return True, "Переход разрешён"
