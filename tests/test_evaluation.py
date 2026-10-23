import json
import unittest
from pathlib import Path

from rag.evaluation import answer_check, retrieval_check, summarize


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {'answerable': True, 'expected_source': 'guide.txt', 'evidence': 'Exact supporting fact',
                     'answer_aliases': [['12 March 2025', '2025-03-12']]}

    def test_retrieval_requires_both_correct_source_and_supporting_text(self):
        wrong = [{'source': 'other.txt', 'text': 'Exact supporting fact'}]
        missing = [{'source': 'guide.txt', 'text': 'Another fact'}]
        self.assertFalse(retrieval_check(self.case, wrong)['hit'])
        self.assertFalse(retrieval_check(self.case, missing)['hit'])
        found = wrong + [{'source': 'guide.txt', 'text': 'Exact supporting fact'}]
        self.assertEqual(retrieval_check(self.case, found), {'hit': True, 'reciprocal_rank': 0.5})

    def test_no_answer_cases_do_not_inflate_retrieval_metrics(self):
        case = {**self.case, 'answerable': False}
        self.assertIsNone(retrieval_check(case, [])['hit'])
        summary = summarize([{'retrieval': retrieval_check(self.case, [])}, {'retrieval': retrieval_check(case, [])}])
        self.assertEqual(summary['answerable_cases'], 1)
        self.assertEqual(summary['evidence_hit_rate_at_4'], 0)

    def test_answer_matching_and_reference_checks_are_separate(self):
        passages = [{'id': 1, 'source': 'guide.txt', 'text': 'Exact supporting fact'}]
        checked = answer_check(self.case, 'The date is 2025-03-12 [99].', passages)
        self.assertTrue(checked['answer_alias_match'])
        self.assertFalse(checked['valid_reference_ids'])
        self.assertFalse(checked['expected_evidence_cited'])
        checked = answer_check(self.case, 'The date is 2025-03-12 [1].', passages)
        self.assertTrue(checked['expected_evidence_cited'])

    def test_benchmark_has_36_cases_with_verifiable_evidence(self):
        directory = Path(__file__).resolve().parents[1] / 'evaluation'
        benchmark = json.loads((directory / 'benchmark.json').read_text())
        cases = benchmark['cases']
        self.assertEqual(len(cases), 36)
        self.assertEqual(len({case['id'] for case in cases}), len(cases))
        self.assertEqual({case['language'] for case in cases}, {'en', 'ru', 'sk'})
        self.assertEqual(sum(not case['answerable'] for case in cases), 8)
        for case in cases:
            if case['answerable']:
                self.assertIn(case['expected_source'], benchmark['documents'])
                self.assertIn(case['evidence'], (directory / 'documents' / case['expected_source']).read_text())
                self.assertTrue(case['answer_aliases'])
            else:
                self.assertIsNone(case['expected_source'])
                self.assertFalse(case['answer_aliases'])
            if case['kind'] == 'follow_up':
                self.assertTrue(case['history'])

    def test_additional_cases_use_new_documents_and_separate_ids(self):
        directory = Path(__file__).resolve().parents[1] / 'evaluation'
        original = json.loads((directory / 'benchmark.json').read_text())
        additional = json.loads((directory / 'followup-check.json').read_text())
        self.assertEqual(len(additional['cases']), 12)
        self.assertFalse({c['id'] for c in original['cases']} & {c['id'] for c in additional['cases']})
        for case in additional['cases']:
            if case['answerable']:
                self.assertNotIn(case['expected_source'], original['documents'])
                text = (directory / 'documents' / case['expected_source']).read_text()
                self.assertIn(case['evidence'], text)


if __name__ == '__main__':
    unittest.main()
