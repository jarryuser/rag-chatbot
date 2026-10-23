import unittest

from rag.queries import MAX_QUERY_CONTEXT, retrieval_query


class QueryTests(unittest.TestCase):
    def test_follow_ups_use_user_topic_in_three_languages(self):
        for question in ['And what is its code?', 'А какой у него код?', 'A aký má kód?']:
            history = [{'role': 'user', 'content': 'Tell me about Cedar'},
                       {'role': 'assistant', 'content': 'Invented code FAKE-123'}]
            query = retrieval_query(question, history)
            self.assertIn('Cedar', query)
            self.assertNotIn('FAKE', query)
            self.assertTrue(query.endswith(question))

    def test_independent_question_does_not_import_previous_topic(self):
        question = 'When did Project Delta launch?'
        self.assertEqual(retrieval_query(question, [{'role': 'user', 'content': 'Cedar'}]), question)

    def test_chained_follow_ups_stop_at_latest_standalone_topic(self):
        history = [{'role': 'user', 'content': text} for text in
                   ['Tell me about Aurora', 'Tell me about Cedar', 'What is its code?']]
        query = retrieval_query('And its date?', history)
        self.assertIn('Cedar', query)
        self.assertNotIn('Aurora', query)

    def test_history_is_bounded_and_optional(self):
        question = 'What is its code?'
        self.assertEqual(retrieval_query(question), question)
        self.assertEqual(retrieval_query(question, [{'role': 'assistant', 'content': 'Cedar'}]), question)
        query = retrieval_query(question, [{'role': 'user', 'content': 'x' * 10000}])
        self.assertLessEqual(len(query), MAX_QUERY_CONTEXT + len(question) + 1)


if __name__ == '__main__':
    unittest.main()
