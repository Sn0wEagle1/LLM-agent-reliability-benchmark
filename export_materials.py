"""Выгрузка фактических запросов и схем инструментов без обращения к LLM."""
import json
from experiments import ROOT,TASKS,CORRECTED_HOLDOUT,CONFIGS_BY_KEY
from src.agent import Agent,SYSTEM_PROMPT,PROMPT_DET,PROMPT_RESTRICT,PROMPT_CONFIRM
from src.tools import ALL_SPECS,to_ollama

class Captured(Exception):pass

class Recorder:
    def chat(self,messages,tools=None,**kwargs):
        self.request=dict(messages=messages,tools=tools,**kwargs)
        raise Captured()

def initial_request(task,cfg):
    recorder=Recorder()
    try:Agent(task,cfg,recorder,1000).run()
    except Captured:return recorder.request
    raise RuntimeError('Начальный запрос не сформирован')

def save(name,value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    (ROOT/'prompts').mkdir(exist_ok=True)
    (ROOT/'docs').mkdir(exist_ok=True)
    for name,value in [('system',SYSTEM_PROMPT),('deterministic',PROMPT_DET),
                       ('rules',PROMPT_RESTRICT),('confirmation',PROMPT_CONFIRM)]:
        (ROOT/'prompts'/f'{name}.txt').write_text(value,encoding='utf-8')
    save('docs/tool_schemas.json',to_ollama(list(ALL_SPECS)))
    catalog=[]
    for task in [*TASKS,*CORRECTED_HOLDOUT]:
        request=initial_request(task,CONFIGS_BY_KEY['base'])
        catalog.append(dict(id=task.id,scenario=task.scenario,title=task.title,prompt=task.prompt,
            user_message=request['messages'][1]['content'],answer_schema=task.answer_schema,
            answer_example=task.answer_example,allowed_tools=task.allowed_tools,faults=task.faults,
            extra_tickets=task.extra_tickets,requires_observation=task.requires_observation))
    save('prompts/tasks.json',catalog)
    cfg=CONFIGS_BY_KEY['combined2']
    save('prompts/initial_request_example.json',dict(task=TASKS[0].id,config=cfg.key,
         **initial_request(TASKS[0],cfg)))
    recorder=Recorder();actor=Agent(TASKS[0],CONFIGS_BY_KEY['verify'],recorder,1000)
    try:actor.llm_verify({'ticket_id':'REQ-101'})
    except Captured:save('prompts/verifier_example.json',recorder.request)
    lines=['# Инструменты','', 'Описание и параметры выгружены из исполняемого кода.', '']
    for name,spec in ALL_SPECS.items():
        lines += [f'## {name}', '',spec['description'],'',
                  'Обязательные параметры: '+(', '.join(spec['required']) or 'нет')+'.','',
                  'Изменение данных: '+('да' if spec['mutating'] else 'нет')+'.','']
    (ROOT/'docs/tools.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Exported 48 tasks, 9 tool schemas and request examples.')

if __name__=='__main__':main()
