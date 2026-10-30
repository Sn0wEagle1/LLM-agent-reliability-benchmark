"""Экспериментальные конфигурации агента (методы из раздела 3 статьи)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    key: str
    name: str
    data_control: bool = False    # контроль извлечённых данных и параметров по схеме
    deterministic: bool = False   # перенос формализованных операций на детерминированные функции
    restrict: bool = False        # ограничение действий = набор инструментов + правила регламента (исходный вариант)
    verify: bool = False          # верификация результатов и состояния
    monitor: bool = False         # контроль выполнения и восстановление
    confirm: bool = False         # подтверждение критических операций пользователем
    tools_only: bool = False      # только ограничение набора инструментов задачи
    rules: bool = False           # только правила регламента (допустимость и порядок действий)
    data_v2: bool = False         # контроль данных v2: проверка сформированного вызова + конкретный отказ
    rules_v2: bool = False        # правила v2: детерминированная проверка похожих незакрытых заявок перед созданием
    ablate: tuple = ()            # отключённые компоненты методов (абляционная серия)

    def has(self, component):
        return component not in self.ablate

    @property
    def limit_tools(self):
        return self.restrict or self.tools_only

    @property
    def check_rules(self):
        return self.restrict or self.rules


CONFIGS = [
    AgentConfig("base", "Базовая"),
    AgentConfig("data", "Контроль данных", data_control=True),
    AgentConfig("det", "Детерминированные функции", deterministic=True),
    AgentConfig("restrict", "Ограничение действий", restrict=True),
    AgentConfig("verify", "Проверка результата", verify=True),
    AgentConfig("monitor", "Мониторинг и восстановление", monitor=True),
    AgentConfig("confirm", "Подтверждение критических действий", confirm=True),
    AgentConfig("combined", "Комбинированная конфигурация", data_control=True, deterministic=True,
                restrict=True, verify=True, monitor=True, confirm=True),
    # дополнительная серия: разделение ограничения действий и экономичные комбинации
    AgentConfig("tools", "Ограничение набора инструментов", tools_only=True),
    AgentConfig("rules", "Правила регламента", rules=True),
    AgentConfig("det_rules", "Детерм. функции + правила", deterministic=True, rules=True),
    AgentConfig("det_mon", "Детерм. функции + мониторинг", deterministic=True, monitor=True),
    AgentConfig("det_rules_mon", "Детерм. функции + правила + мониторинг", deterministic=True, rules=True,
                monitor=True),
    # серия 3: доработанные методы (контроль данных v2, правила регламента v2)
    AgentConfig("data2", "Контроль данных v2", data_control=True, data_v2=True),
    AgentConfig("det_rules2", "Детерм. функции v2", deterministic=True, rules=True, rules_v2=True),
    AgentConfig("det_rules_mon2", "Детерм. функции v2 + контроль выполнения", deterministic=True, rules=True,
                rules_v2=True, monitor=True),
    AgentConfig("det_rules_mon_data2", "Детерм. функции v2 + контроль выполнения + контроль данных v2",
                deterministic=True, rules=True, rules_v2=True, monitor=True, data_control=True, data_v2=True),
    AgentConfig("combined2", "Комбинированная v2", data_control=True, data_v2=True, deterministic=True,
                restrict=True, rules_v2=True, verify=True, monitor=True, confirm=True),
]

# серия 4 (абляция): полная комбинация без одного компонента
_FULL = dict(data_control=True, data_v2=True, deterministic=True, restrict=True, rules_v2=True, verify=True,
             monitor=True, confirm=True)
ABLATIONS = [
    ("normalize", "без нормализации параметров"),
    ("dupcheck", "без проверки дубликатов"),
    ("keyword", "без поиска по ключевым словам"),
    ("schema", "без проверки схемы вызова"),
    ("diagnosis", "без диагностики некорректного вызова"),
    ("loopblock", "без блокировки повторов"),
    ("autoretry", "без автоматического повтора"),
    ("pending", "без проверки состояния после неполного ответа"),
]
for _comp, _label in ABLATIONS:
    _kw = dict(_FULL, rules_v2=False) if _comp == "dupcheck" else dict(_FULL, ablate=(_comp,))
    CONFIGS.append(AgentConfig("abl_" + _comp, "Комбинированная " + _label, **_kw))

CONFIGS_BY_KEY = {c.key: c for c in CONFIGS}

# Общие ограничения цикла агента
MAX_ITER_BASE = 15      # аварийный предел, одинаковый для всех конфигураций без мониторинга
MAX_ITER_MONITOR = 10   # предел, задаваемый механизмом мониторинга
MAX_RETRIES = 2         # допустимое число повторов одной операции при мониторинге
MAX_ANSWER_CORRECTIONS = 3
MAX_VERIFIER_ROUNDS = 2
