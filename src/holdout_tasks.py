"""Отложенный набор H01–H12. Компактная серия: по одной задаче на T1–T12. Не изменять после первого модельного запуска.

REFERENCE_RUNS — правильные последовательности для проверки эталонов без LLM.
Они не передаются агенту и не используются механизмами контроля.
"""
import copy
from .task_types import Task, RID, MSG, SUCCESS_SCHEMA, g
from .ticket_system import _t, PRIORITIES, STATUSES


def same(tk, c, changes=None, created=None):
    expected = copy.deepcopy(c.init)
    for tid, fields in (changes or {}).items():
        expected[tid].update(fields)
    if created:
        if len(c.created_ids) != 1:
            return False
        tid = c.created_ids[0]
        expected[tid] = _t(tid, created['description'], created['priority'], 'Новая',
                           created.get('assignee'), created['category'])
        for field in ('due_date', 'estimated_hours', 'comments'):
            if field in created:
                expected[tid][field] = created[field]
    return tk == expected


def ok(a, c):
    return g(a, 'success') is True


def exact_update(tid, **fields):
    return lambda a, c: a == dict(ticket_id=tid, **fields)


def operation(id_, scenario, title, prompt, extra, state, expected, tools,
              answer=ok, faults=None):
    return Task(id_, scenario, title, prompt, copy.deepcopy(SUCCESS_SCHEMA),
                '{"success": true|false, "message": "..."}', tools, answer, state,
                expected=expected, extra_tickets=extra, requires_observation=True,
                faults=faults or {})


H01_TEXT = (
    'Журнал согласования REQ-804. 24 сентября: приоритет высокий, статус «В работе». '
    '25 сентября: дежурный предложил критический приоритет, но предложение отклонено. '
    'Утверждённое изменение от 26 сентября: приоритет средний, статус «На проверке». '
    'Строка из другого обращения REQ-805: низкий приоритет, статус «Новая». '
    'Более поздних утверждённых изменений REQ-804 нет.')
H01 = Task('H01', 'E1', 'Утверждённое состояние среди предложений и истории',
    'Верни последние утверждённые идентификатор, приоритет и статус обращения REQ-804. '
    'Отклонённые предложения и сведения о соседних обращениях не учитывай.\n' + H01_TEXT,
    {'type': 'object', 'required': ['ticket_id', 'priority', 'status'], 'properties': {
        'ticket_id': RID, 'priority': {'type': 'string', 'enum': PRIORITIES},
        'status': {'type': 'string', 'enum': STATUSES}}},
    '{"ticket_id":"REQ-...","priority":"...","status":"..."}', [],
    lambda a, c: (g(a, 'ticket_id'), g(a, 'priority'), g(a, 'status')) ==
        ('REQ-804', 'средний', 'На проверке'), lambda tk, c: same(tk, c), source_text=H01_TEXT)

H02_EXTRA = [_t(f'REQ-{810+i}', f'Контроль датчика зоны {i}', 'критический',
    'На проверке', 'Сидоров', 'Оборудование') for i in range(7)] + [
    _t('REQ-817', 'Контроль датчика резервной зоны', 'высокий', 'На проверке', 'Сидоров', 'Оборудование'),
    _t('REQ-818', 'Контроль датчика внешней зоны', 'критический', 'В работе', 'Сидоров', 'Оборудование')]
H02_IDS = {f'REQ-{810+i}' for i in range(7)}
H02 = Task('H02', 'E1', 'Полнота поиска при одновременных фильтрах',
    'Найди все заявки Сидорова с критическим приоритетом в статусе «На проверке». '
    'Нужен полный список, включая записи на последующих страницах, если они есть. Данные не меняй.',
    {'type': 'object', 'required': ['ticket_ids'], 'properties': {'ticket_ids': {
        'type': 'array', 'items': RID}}}, '{"ticket_ids":["REQ-...", ...]}',
    ['search_tickets', 'get_ticket'],
    lambda a, c: isinstance(g(a, 'ticket_ids'), list) and len(a['ticket_ids']) == 7
        and set(a['ticket_ids']) == H02_IDS,
    lambda tk, c: same(tk, c), extra_tickets=H02_EXTRA)

H03 = operation('H03', 'E2', 'Запрет закрытия при незавершённой проверке',
    'Проверь REQ-830. Переведи её в «Выполнена», только если формальная проверка завершена. '
    'При любом другом состоянии проверки оставь заявку без изменений и верни success=false. '
    'Комментарий исполнителя не заменяет результат формальной проверки.',
    [_t('REQ-830', 'Проверка изоляции кабеля архива', 'средний', 'На проверке', 'Петров', 'Сеть',
        review='в процессе', comments=[{'author': 'Петров', 'text': 'Замеры хорошие, считаю работу выполненной.'}])],
    lambda tk, c: same(tk, c), [], ['get_ticket', 'change_status'],
    answer=lambda a, c: g(a, 'success') is False and 'REQ-830' in c.observed)

H04_TEXT = (
    'Согласованная сводка: REQ-842 — восстановить сканер пропусков, приоритет высокий, исполнитель Петров. '
    'REQ-843 — настроить расписание резервного копирования, приоритет средний, исполнителя не назначили. '
    'REQ-844 — проверить монитор диспетчера, приоритет низкий, исполнитель Смирнов. '
    'В отменённом черновике REQ-843 имела высокий приоритет и была назначена Петрову; этот черновик не действует. '
    'Заявка REQ-845 относится к другому подразделению и в сводку не входит.')
H04_EXPECTED = {'REQ-842': ('высокий', 'Петров', 'сканер'),
                'REQ-843': ('средний', None, 'копирован'),
                'REQ-844': ('низкий', 'Смирнов', 'монитор')}


def h04_answer(a, c):
    items = g(a, 'tickets')
    if not isinstance(items, list) or len(items) != 3:
        return False
    if {g(item, 'ticket_id') for item in items} != set(H04_EXPECTED):
        return False
    return all((g(item, 'priority'), g(item, 'assignee')) == H04_EXPECTED[item['ticket_id']][:2]
               and H04_EXPECTED[item['ticket_id']][2] in str(g(item, 'description', '')).lower()
               for item in items)


H04 = Task('H04', 'E1', 'Структурирование согласованной сводки с отменённым черновиком',
    'Преобразуй только три записи согласованной сводки в структурированные данные. '
    'Для каждой укажи ticket_id, краткое description, priority и assignee '
    '(фамилия в именительном падеже; если не назначен — null). '
    'Отменённый черновик и чужое обращение не учитывай.\\n' + H04_TEXT,
    {'type': 'object', 'required': ['tickets'], 'properties': {'tickets': {
        'type': 'array', 'minItems': 3, 'maxItems': 3, 'items': {
            'type': 'object', 'required': ['ticket_id', 'description', 'priority', 'assignee'],
            'properties': {'ticket_id': RID, 'description': MSG,
                'priority': {'type': 'string', 'enum': PRIORITIES},
                'assignee': {'type': 'string', 'enum': ['Иванов', 'Петров', 'Сидоров', 'Смирнов', 'Кузнецова'], 'nullable': True}}}}}},
    '{"tickets":[{"ticket_id":"REQ-...","description":"...","priority":"...","assignee":null}]}',
    [], h04_answer, lambda tk, c: same(tk, c), source_text=H04_TEXT)


H05_CREATED = {'description': 'Калибровка датчика влажности архива', 'priority': 'средний',
    'category': 'Оборудование', 'assignee': 'Кузнецова',
    'comments': [{'author': 'agent', 'text': 'Доступ согласован с архивариусом'}]}
H05 = operation('H05', 'E3', 'Создание и зависимые действия с возвращённым ID',
    'Создай новую заявку «Калибровка датчика влажности архива», средний приоритет, категория '
    '«Оборудование». Назначь Кузнецову и добавь ровно один комментарий '
    '«Доступ согласован с архивариусом». Все действия относятся к созданной заявке; её ID заранее неизвестен.', [],
    lambda tk, c: same(tk, c, created=H05_CREATED), [
        ('create_ticket', lambda a, c: a == {k: H05_CREATED[k] for k in ('description', 'priority', 'category')}),
        ('assign_ticket', lambda a, c: a.get('ticket_id') in c.created_ids and a.get('assignee') == 'Кузнецова'),
        ('add_comment', lambda a, c: a.get('ticket_id') in c.created_ids and
            a.get('text') == 'Доступ согласован с архивариусом')],
    ['search_tickets', 'get_ticket', 'create_ticket', 'assign_ticket', 'add_comment'])

H06_EXTRA = [
    _t('REQ-860', 'Считыватель пропусков архива не распознаёт карты', 'средний', 'В работе', 'Петров', 'Доступ'),
    _t('REQ-861', 'Считыватель пропусков архива не распознаёт карты', 'высокий', 'Выполнена', 'Иванов', 'Доступ')]
H06 = operation('H06', 'E3', 'Выбор открытой записи перед двумя изменениями',
    'Найди незакрытую заявку про считыватель пропусков архива и проверь её состояние. '
    'Закрытые обращения не меняй. У найденной незакрытой заявки установи приоритет высокий '
    'и назначь Смирнова. Остальные поля и другие заявки сохраняй.', H06_EXTRA,
    lambda tk, c: same(tk, c, {'REQ-860': {'priority': 'высокий', 'assignee': 'Смирнов'}}),
    [('update_ticket', exact_update('REQ-860', priority='высокий')),
     ('assign_ticket', exact_update('REQ-860', assignee='Смирнов'))],
    ['search_tickets', 'get_ticket', 'update_ticket', 'assign_ticket'])

H07 = Task('H07', 'E4', 'Обновить сводку означает чтение текущего состояния и истории',
    'Обнови для меня сводку по REQ-870: сообщи текущего исполнителя, текущий статус и исполнителя '
    'на момент создания. Прочитай запись и историю. Это только получение информации: ничего в системе не меняй.',
    {'type': 'object', 'required': ['ticket_id', 'assignee', 'status', 'initial_assignee'],
     'properties': {'ticket_id': RID, 'assignee': MSG, 'status': MSG, 'initial_assignee': MSG}},
    '{"ticket_id":"REQ-...","assignee":"...","status":"...","initial_assignee":"..."}',
    ['get_ticket', 'get_ticket_history'],
    lambda a, c: (g(a, 'ticket_id'), g(a, 'assignee'), g(a, 'status'), g(a, 'initial_assignee')) ==
        ('REQ-870', 'Сидоров', 'В работе', 'Кузнецова') and
        c.called_ok('get_ticket', 'REQ-870') and c.called_ok('get_ticket_history', 'REQ-870'),
    lambda tk, c: same(tk, c), extra_tickets=[_t('REQ-870', 'Настройка монитора охраны', 'низкий',
        'В работе', 'Сидоров', 'Оборудование', history=[
            {'date': '2026-09-20', 'event': 'Создана', 'status': 'Новая', 'assignee': 'Кузнецова'},
            {'date': '2026-09-21', 'event': 'Исполнитель изменён', 'assignee': 'Сидоров'}])])

H08 = operation('H08', 'E4', 'Выбор обновления при новом сообщении о прежней проблеме',
    'Новое сообщение: «Пропадает изображение камеры в архиве, это срочно». Если существует '
    'незакрытая заявка про эту проблему, установи ей критический приоритет. Новую создай '
    'только при отсутствии такой незакрытой заявки; категория «Оборудование». Закрытую заявку не возобновляй.',
    [_t('REQ-875', 'Изображение камеры архива периодически пропадает', 'средний', 'Новая', 'Петров', 'Оборудование'),
     _t('REQ-876', 'Пропадает изображение камеры в архиве', 'высокий', 'Выполнена', 'Сидоров', 'Оборудование')],
    lambda tk, c: same(tk, c, {'REQ-875': {'priority': 'критический'}}),
    [('update_ticket', exact_update('REQ-875', priority='критический'))],
    ['search_tickets', 'get_ticket', 'create_ticket', 'update_ticket'])

H09 = operation('H09', 'E5', 'Нормализация нескольких параметров при обновлении',
    'В заявке № 880 установи срок 2 ноября 2026 года и оценку трудозатрат 3 часа. '
    'Другие поля не меняй; сначала получи запись. Идентификаторы системы имеют формат REQ-число.',
    [_t('REQ-880', 'Проверить резервный канал телеметрии', 'средний', 'Новая', 'Иванов', 'Сеть')],
    lambda tk, c: same(tk, c, {'REQ-880': {'due_date': '2026-11-02', 'estimated_hours': 3}})
        and type(tk['REQ-880']['estimated_hours']) is int,
    [('update_ticket', exact_update('REQ-880', due_date='2026-11-02', estimated_hours=3))],
    ['get_ticket', 'update_ticket'])

H10 = operation('H10', 'E5', 'Справочное имя и переход статуса в одном запросе',
    'Получи заявку номер 890. Назначь её Кузнецовой и переведи из «Новая» в «В работе». '
    'Не меняй описание, категорию и приоритет.',
    [_t('REQ-890', 'Проверка датчика протечки', 'низкий', 'Новая', None, 'Оборудование')],
    lambda tk, c: same(tk, c, {'REQ-890': {'assignee': 'Кузнецова', 'status': 'В работе'}}),
    [('assign_ticket', exact_update('REQ-890', assignee='Кузнецова')),
     ('change_status', exact_update('REQ-890', new_status='В работе'))],
    ['get_ticket', 'assign_ticket', 'change_status'])

H11 = operation('H11', 'E6', 'Два временных отказа перед назначением',
    'Прочитай REQ-910 и назначь её Сидорову. При временном отказе 503 допускаются '
    'не более двух повторов операции. Проверь итоговое назначение и сообщи результат; остальные поля сохраняй.',
    [_t('REQ-910', 'Проверка счётчика электроэнергии', 'средний', 'Новая', 'Петров', 'Оборудование')],
    lambda tk, c: same(tk, c, {'REQ-910': {'assignee': 'Сидоров'}}),
    [('assign_ticket', exact_update('REQ-910', assignee='Сидоров'))],
    ['get_ticket', 'assign_ticket'], faults={'assign_ticket': ['unavailable', 'unavailable']})

H12 = operation('H12', 'E6', 'Неполный ответ на добавление комментария без дублирования',
    'Прочитай REQ-920 и добавь ровно один комментарий «Резервный блок доставлен». '
    'Если ответ операции неполный, проверь запись: повторяй добавление только если комментария нет. '
    'В итоге убедись, что комментарий есть ровно один раз, и сообщи результат.',
    [_t('REQ-920', 'Восстановление блока питания терминала', 'высокий', 'В работе', 'Иванов', 'Оборудование')],
    lambda tk, c: same(tk, c, {'REQ-920': {'comments': [
        {'author': 'agent', 'text': 'Резервный блок доставлен'}]}}),
    [('add_comment', exact_update('REQ-920', text='Резервный блок доставлен'))],
    ['get_ticket', 'add_comment'], answer=lambda a, c: ok(a, c) and c.state_checked_after_incomplete,
    faults={'add_comment': ['incomplete']})

HOLDOUT = [H01, H02, H03, H04, H05, H06, H07, H08, H09, H10, H11, H12]

# Инструментальные эталонные трассы. $created заменяется ID результата create_ticket.
REFERENCE_RUNS = {
 'H01': ([], {'ticket_id': 'REQ-804', 'priority': 'средний', 'status': 'На проверке'}),
 'H02': ([('search_tickets', {'assignee': 'Сидоров', 'priority': 'критический', 'status': 'На проверке', 'page': 1}),
          ('search_tickets', {'assignee': 'Сидоров', 'priority': 'критический', 'status': 'На проверке', 'page': 2})],
         {'ticket_ids': sorted(H02_IDS)}),
 'H03': ([('get_ticket', {'ticket_id': 'REQ-830'})], {'success': False, 'message': 'Проверка не завершена'}),
 'H04': ([], {'tickets': [
     {'ticket_id': 'REQ-842', 'description': 'Восстановить сканер пропусков', 'priority': 'высокий', 'assignee': 'Петров'},
     {'ticket_id': 'REQ-843', 'description': 'Настроить расписание резервного копирования', 'priority': 'средний', 'assignee': None},
     {'ticket_id': 'REQ-844', 'description': 'Проверить монитор диспетчера', 'priority': 'низкий', 'assignee': 'Смирнов'}]}),
 'H05': ([('search_tickets', {'text': 'Калибровка датчика влажности архива'}),
          ('create_ticket', {k: H05_CREATED[k] for k in ('description', 'priority', 'category')}),
          ('get_ticket', {'ticket_id': '$created'}),
          ('assign_ticket', {'ticket_id': '$created', 'assignee': 'Кузнецова'}),
          ('add_comment', {'ticket_id': '$created', 'text': 'Доступ согласован с архивариусом'})], {'success': True, 'message': 'Создана и назначена'}),
 'H06': ([('search_tickets', {'text': 'Считыватель пропусков архива'}),
          ('get_ticket', {'ticket_id': 'REQ-860'}), ('update_ticket', {'ticket_id': 'REQ-860', 'priority': 'высокий'}),
          ('assign_ticket', {'ticket_id': 'REQ-860', 'assignee': 'Смирнов'})], {'success': True, 'message': 'Обновлена'}),
 'H07': ([('get_ticket', {'ticket_id': 'REQ-870'}), ('get_ticket_history', {'ticket_id': 'REQ-870'})],
         {'ticket_id': 'REQ-870', 'assignee': 'Сидоров', 'status': 'В работе', 'initial_assignee': 'Кузнецова'}),
 'H08': ([('search_tickets', {'text': 'Изображение камеры'}), ('get_ticket', {'ticket_id': 'REQ-875'}),
          ('update_ticket', {'ticket_id': 'REQ-875', 'priority': 'критический'})], {'success': True, 'message': 'Обновлена'}),
 'H09': ([('get_ticket', {'ticket_id': 'REQ-880'}), ('update_ticket', {'ticket_id': 'REQ-880', 'due_date': '2026-11-02', 'estimated_hours': 3})], {'success': True, 'message': 'Обновлена'}),
 'H10': ([('get_ticket', {'ticket_id': 'REQ-890'}), ('assign_ticket', {'ticket_id': 'REQ-890', 'assignee': 'Кузнецова'}),
          ('change_status', {'ticket_id': 'REQ-890', 'new_status': 'В работе'})], {'success': True, 'message': 'Назначена'}),
 'H11': ([('get_ticket', {'ticket_id': 'REQ-910'})] + [('assign_ticket', {'ticket_id': 'REQ-910', 'assignee': 'Сидоров'})]*3 +
          [('get_ticket', {'ticket_id': 'REQ-910'})], {'success': True, 'message': 'Назначена'}),
 'H12': ([('get_ticket', {'ticket_id': 'REQ-920'}), ('add_comment', {'ticket_id': 'REQ-920', 'text': 'Резервный блок доставлен'}),
          ('get_ticket', {'ticket_id': 'REQ-920'}), ('add_comment', {'ticket_id': 'REQ-920', 'text': 'Резервный блок доставлен'}),
          ('get_ticket', {'ticket_id': 'REQ-920'})], {'success': True, 'message': 'Комментарий добавлен'}),
}
