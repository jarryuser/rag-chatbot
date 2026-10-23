"""Deterministic checks; answer matching is a diagnostic, not a correctness judge."""

import re
import unicodedata


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def retrieval_check(case, passages):
    if not case['answerable']:
        return {'hit': None, 'reciprocal_rank': None}
    for rank, passage in enumerate(passages, start=1):
        if (passage['source'] == case['expected_source'] and
                normalize(case['evidence']) in normalize(passage['text'])):
            return {'hit': True, 'reciprocal_rank': 1 / rank}
    return {'hit': False, 'reciprocal_rank': 0}


def answer_check(case, answer, passages):
    text = normalize(answer)
    references = {int(value) for value in re.findall(r'\[(\d+)\]', answer)}
    valid = {passage['id'] for passage in passages}
    supported_ids = {passage['id'] for passage in passages if case['answerable']
                     and passage['source'] == case['expected_source']
                     and normalize(case['evidence']) in normalize(passage['text'])}
    abstention_markers = ['not enough information', 'insufficient information', 'does not contain',
                          'not provided', 'not specified', 'not mentioned', 'cannot determine',
                          'не указано', 'не содержит', 'недостаточно', 'не указан', 'нет информации',
                          'не могу определить', 'nie je uveden', 'neobsahuje', 'nedostatok informáci',
                          'nie sú uveden', 'nie je možné určiť', 'nemám dostatok']
    return {
        'answer_alias_match': (all(any(normalize(alias) in text for alias in group)
                                   for group in case['answer_aliases']) if case['answerable'] else None),
        'abstention_marker': (any(marker in text for marker in abstention_markers)
                              if not case['answerable'] else None),
        'valid_reference_ids': bool(references) and references.issubset(valid),
        'expected_evidence_cited': bool(references & supported_ids) if case['answerable'] else None,
    }


def summarize(rows):
    applicable = [row for row in rows if row['retrieval']['hit'] is not None]
    errors = [row for row in rows if row.get('error')]
    answer_rows = [row for row in rows if 'answer_checks' in row]
    answerable = [row for row in answer_rows if row['answer_checks']['answer_alias_match'] is not None]
    unknown = [row for row in answer_rows if row['answer_checks']['abstention_marker'] is not None]
    return {
        'cases': len(rows), 'errors': len(errors), 'answerable_cases': len(applicable),
        'evidence_hit_rate_at_4': sum(row['retrieval']['hit'] for row in applicable) / len(applicable) if applicable else None,
        'mean_reciprocal_rank': sum(row['retrieval']['reciprocal_rank'] for row in applicable) / len(applicable) if applicable else None,
        'answer_alias_match_rate': sum(row['answer_checks']['answer_alias_match'] for row in answerable) / len(answerable) if answerable else None,
        'abstention_marker_rate': sum(row['answer_checks']['abstention_marker'] for row in unknown) / len(unknown) if unknown else None,
        'answer_checks_completed': len(answer_rows),
    }
