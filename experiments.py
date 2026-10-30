"""Наборы запусков, соответствующие сериям статьи."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from src.configs import CONFIGS_BY_KEY
from src.tasks import TASKS
from src.holdout_tasks import HOLDOUT, REFERENCE_RUNS

MAIN_KEYS = ['base', 'data2', 'det_rules2', 'tools', 'verify', 'monitor', 'confirm',
             'det_rules_mon2', 'det_rules_mon_data2', 'combined2']
HOLDOUT_KEYS = ['base', 'det_rules2', 'det_rules_mon2', 'det_rules_mon_data2', 'combined2']
Q8_KEYS = ['base', 'det_rules_mon2', 'combined2']
ABLATION_KEYS = ['combined2', 'abl_normalize', 'abl_dupcheck', 'abl_keyword', 'abl_schema',
                 'abl_diagnosis', 'abl_loopblock', 'abl_autoretry', 'abl_pending']
GENERAL = replace(CONFIGS_BY_KEY['det_rules2'], key='det_general',
                  name='Общие детерминированные функции', rules_v2=False, ablate=('keyword',))
CORRECTED_HOLDOUT = deepcopy(HOLDOUT)
# Создание записи не требует предварительного чтения несуществующего идентификатора.
next(t for t in CORRECTED_HOLDOUT if t.id == 'H05').requires_observation = False
SERIES = ('main', 'q8', 'ablation', 'holdout', 'general_df', 'extra_seed')


def jobs(series):
    if series == 'main': tasks, keys, reps = TASKS, MAIN_KEYS, range(2)
    elif series == 'q8': tasks, keys, reps = TASKS, Q8_KEYS, range(1)
    elif series == 'ablation': tasks, keys, reps = TASKS, ABLATION_KEYS, range(1)
    elif series == 'holdout': tasks, keys, reps = CORRECTED_HOLDOUT, HOLDOUT_KEYS, range(2)
    elif series == 'general_df': tasks, keys, reps = TASKS, ['det_general'], range(2)
    elif series == 'extra_seed': tasks, keys, reps = TASKS, ['base'], range(2, 5)
    else: raise ValueError(series)
    for rep in reps:
        for index, task in enumerate(tasks):
            seed = (20000 if series == 'holdout' else 1000) + 97 * rep + index
            for key in keys:
                yield task, GENERAL if key == 'det_general' else CONFIGS_BY_KEY[key], rep, seed
