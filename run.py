"""Запуск выбранной серии через локальный сервер Ollama."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from experiments import ROOT, SERIES, jobs
from src.agent import Agent
from src.llm import LLM


def api(path, body=None):
    payload = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request('http://localhost:11434/api/' + path, data=payload,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--series', choices=SERIES, default='main')
    p.add_argument('--model', help='Тег модели в локальном Ollama')
    p.add_argument('--out', type=Path, default=ROOT / 'runs')
    p.add_argument('--tasks', help='Идентификаторы через запятую')
    p.add_argument('--configs', help='Ключи конфигураций через запятую')
    p.add_argument('--plan', action='store_true', help='Показать план без обращения к модели')
    args = p.parse_args()
    schedule = list(jobs(args.series))
    for attr, idx, field in [('tasks', 0, 'id'), ('configs', 1, 'key')]:
        value = getattr(args, attr)
        if value:
            selected = set(value.split(','))
            unknown = selected - {getattr(j[idx], field) for j in schedule}
            if unknown: p.error(f'Неизвестные {attr}: {sorted(unknown)}')
            schedule = [j for j in schedule if getattr(j[idx], field) in selected]
    print(f'{args.series}: {len(schedule)} запусков')
    if args.plan:
        for task, cfg, rep, seed in schedule:
            print(task.id, cfg.key, f'rep={rep}', f'seed={seed}')
        return
    if (ROOT / 'results').resolve() in (args.out.resolve(), *args.out.resolve().parents):
        p.error('Каталог results содержит опубликованные данные; выберите другой --out')
    model = args.model or ('qwen3:14b-q8_0' if args.series == 'q8' else 'qwen3:14b')
    models = api('tags')['models']
    info = next((m for m in models if m['name'] == model), None)
    if info is None: p.error(f'Модель {model} не найдена в Ollama')
    expected_quant = 'Q8_0' if args.series == 'q8' else 'Q4_K_M'
    if info.get('details', {}).get('quantization_level') != expected_quant:
        p.error(f'Для серии требуется {expected_quant}')
    client = LLM(model)
    hashes = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in sorted((ROOT / 'src').glob('*.py')) + [ROOT / 'experiments.py', ROOT / 'run.py']}
    identity = {'series': args.series, 'model': model, 'digest': info['digest'],
                'options': client.options, 'think': client.think, 'source_sha256': hashes,
                'schedule': [(t.id, c.key, rep, seed) for t, c, rep, seed in schedule]}
    identity = json.loads(json.dumps(identity))
    out = args.out / args.series
    out.mkdir(parents=True, exist_ok=True)
    lock = out / '.running'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        p.error(f'Каталог занят: {lock}. После аварии удалите файл только убедившись, что процесс завершён.')
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    try:
        manifest_path = out / 'manifest.json'
        result_path = out / 'results.jsonl'
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest['identity'] != identity: raise ValueError('Параметры возобновления не совпадают')
        else:
            if result_path.exists(): raise ValueError('Файл результатов существует без манифеста')
            manifest = {'identity': identity, 'created_at': datetime.now(timezone.utc).isoformat(),
                        'ollama': api('version'), 'model_show': api('show', {'model': model}),
                        'configurations': {c.key: asdict(c) for _, c, _, _ in schedule}}
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        planned = {(t.id, c.key, rep, seed) for t, c, rep, seed in schedule}
        done = set()
        if result_path.exists():
            for line in result_path.read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                key = row['task'], row['config'], row['rep'], row['seed']
                if key not in planned or key in done or row['model_digest'] != info['digest']:
                    raise ValueError('Несогласованные или повторные записи результатов')
                done.add(key)
        if len(done) == len(schedule): print('Серия уже завершена'); return
        client.chat([{'role': 'user', 'content': 'Ответь одним словом: готов.'}], seed=999)
        for task, cfg, rep, seed in schedule:
            key = task.id, cfg.key, rep, seed
            if key in done: continue
            result = Agent(task, cfg, client, seed).run()
            result.update(task=task.id, scenario=task.scenario, config=cfg.key, config_name=cfg.name,
                          rep=rep, seed=seed, model=model, model_digest=info['digest'], series=args.series)
            with result_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(result, ensure_ascii=False) + '\n')
                stream.flush(); os.fsync(stream.fileno())
            done.add(key)
            print(f'{len(done)}/{len(schedule)} {task.id} {cfg.key}: {result["success"]}', flush=True)
    finally:
        lock.unlink()


if __name__ == '__main__':
    main()
