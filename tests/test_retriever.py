import asyncio
import importlib.util
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('sentence_transformers'), 'requires ML dependencies')
class RetrieverTests(unittest.TestCase):
    def test_sync_and_stream_use_same_history_and_evidence(self):
        from langchain_core.documents import Document
        from langchain_core.runnables import RunnableLambda
        from rag import retriever

        docs = [Document(page_content='The review code is ABC-12.', metadata={'source': 'review.txt'})]
        history = [{'role': 'user', 'content': 'Tell me about the review.'}]
        question = 'What is its code?'
        received = []

        def answer(messages):
            received.append(messages)
            return 'ABC-12 [1]'

        async def stream():
            return [event async for event in retriever.stream_answer(question, history=history)]

        with patch.object(retriever, 'retrieve_documents', return_value=docs) as search, \
                patch.object(retriever, '_build_llm', return_value=RunnableLambda(answer)):
            result = retriever.get_answer(question, history=history)
            events = asyncio.run(stream())
        self.assertEqual(search.call_count, 2)
        for call in search.call_args_list:
            self.assertEqual(call.kwargs['history'], history)
        self.assertEqual(received[0], received[1])
        self.assertEqual(received[0][-1].content, question)
        self.assertIn('ABC-12', received[0][0].content)
        self.assertEqual(events[0]['type'], 'sources')
        self.assertEqual(events[-1]['type'], 'done')
        self.assertEqual(events[0]['citations'], result['citations'])
        self.assertEqual(''.join(e['content'] for e in events if e['type'] == 'token'), result['answer'])

    def test_vector_hybrid_and_rerank_share_contextual_query(self):
        from unittest.mock import Mock
        from rag import retriever
        question = 'What is its code?'
        history = [{'role': 'user', 'content': 'Tell me about Larch.'}]
        expected = 'Tell me about Larch.\n' + question
        store = Mock()
        store._collection.count.return_value = 10
        store.similarity_search.return_value = list(range(6))
        with patch.object(retriever, '_load_vectorstore', return_value=store), \
                patch.object(retriever, '_resolve_parents', side_effect=lambda docs, session: docs), \
                patch.object(retriever, '_hybrid_retrieve', return_value=list(range(6))) as hybrid, \
                patch.object(retriever, '_rerank', return_value=[1]) as rerank:
            for method in ['vector', 'hybrid', 'reranked']:
                retriever.retrieve_documents(question, method=method, history=history)
        store.similarity_search.assert_called_once_with(expected, k=retriever.TOP_K)
        self.assertTrue(all(call.args[0] == expected for call in hybrid.call_args_list))
        self.assertEqual(rerank.call_args.args[0], expected)


if __name__ == '__main__':
    unittest.main()
