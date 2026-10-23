"""Run the synthetic benchmark without touching user documents or their index."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT / 'evaluation' / 'benchmark.json')
    parser.add_argument('--answers', action='store_true', help='Also call the configured provider')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--delay', type=float, default=10, help='Seconds between provider requests')
    parser.add_argument('--output', type=Path, default=Path('/tmp/rag-evaluation.json'))
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error('--limit must be positive')
    if args.delay < 0:
        parser.error('--delay must not be negative')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from rag import ingestor, retriever, parents
    from rag.citations import build_citations
    from rag.queries import retrieval_query
    from rag.evaluation import retrieval_check, answer_check, summarize

    if args.answers and os.getenv('LLM_PROVIDER', 'groq') == 'groq':
        from groq import Groq
        available = {model.id for model in Groq(timeout=15, max_retries=0).models.list().data}
        model = os.getenv('LLM_MODEL', retriever.LLM_MODEL)
        if model not in available:
            raise RuntimeError('Configured model is unavailable. Set LLM_MODEL to an accessible model.')
    fixture = args.dataset.resolve().parent
    dataset_bytes = args.dataset.read_bytes()
    dataset = json.loads(dataset_bytes)
    digest = hashlib.sha256(dataset_bytes)
    for filename in dataset['documents']:
        digest.update((fixture / 'documents' / filename).read_bytes())
    report = {'dataset_sha256': digest.hexdigest(), 'dataset_version': dataset['version'],
              'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
              'embedding_model': 'sentence-transformers/all-MiniLM-L6-v2',
              'reranker_model': retriever.RERANKER_MODEL,
              'provider': os.getenv('LLM_PROVIDER', 'groq') if args.answers else None,
              'model': ((os.getenv('OLLAMA_MODEL', 'llama3.2') if os.getenv('LLM_PROVIDER', 'groq') == 'ollama'
                         else os.getenv('LLM_MODEL', retriever.LLM_MODEL)) if args.answers else None),
              'notes': 'Answer aliases and abstention markers are heuristics; inspect raw answers. Unanswerable cases have no retrieval accuracy score.',
              'results': []}
    cases = dataset['cases'][:args.limit] if args.limit else dataset['cases']
    with tempfile.TemporaryDirectory(prefix='rag-evaluation-') as directory:
        for module in [ingestor, retriever, parents]:
            module.CHROMA_BASE_DIR = directory
        session_id = 'default'
        for filename in dataset['documents']:
            ingestor.ingest(str(fixture / 'documents' / filename), display_name=filename, session_id=session_id)
        for index, case in enumerate(cases):
            for method in ['vector', 'hybrid', 'reranked']:
                started = time.monotonic()
                passages = build_citations(retriever.retrieve_documents(case['question'], session_id, method=method, history=case['history']))
                row = {'id': case['id'], 'method': method, 'kind': case['kind'], 'language': case['language'],
                       'question': case['question'], 'retrieval_query': retrieval_query(case['question'], case['history']),
                       'retrieval': retrieval_check(case, passages),
                       'retrieval_seconds': round(time.monotonic() - started, 4), 'passages': passages}
                report['results'].append(row)
                if args.answers and method == 'reranked':
                    try:
                        answer = retriever.get_answer(case['question'], session_id, history=case['history'])
                        row['answer'] = answer['answer']
                        row['answer_passages'] = answer['citations']
                        row['answer_checks'] = answer_check(case, answer['answer'], answer['citations'])
                    except Exception as exc:
                        row['error'] = type(exc).__name__
                    if index < len(cases) - 1:
                        time.sleep(max(0, args.delay))
            print(f"{index + 1}/{len(cases)} {case['id']} {case['kind']}", flush=True)
            report['summary'] = {method: summarize([row for row in report['results'] if row['method'] == method])
                                 for method in ['vector', 'hybrid', 'reranked']}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['summary'], indent=2), flush=True)
    print(f'Report: {args.output}', flush=True)
    if any(row.get('error') for row in report['results']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
