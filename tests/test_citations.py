import unittest
from types import SimpleNamespace

from rag.citations import build_citations, format_context, format_sources


def doc(text, **metadata):
    return SimpleNamespace(page_content=text, metadata=metadata)


class CitationTests(unittest.TestCase):
    def test_pdf_pages_are_one_based_and_exact_text_is_preserved(self):
        passage = 'Project Aurora launched on 12 March 2025.\nCoordinator: Elena Novak.'
        citations = build_citations([doc(passage, source='guide.pdf', page=1)])
        self.assertEqual(citations[0]['page'], 2)
        self.assertEqual(citations[0]['id'], 1)
        self.assertEqual(citations[0]['text'], passage)
        self.assertEqual(format_sources([doc(passage, source='guide.pdf', page=1)]), 'guide.pdf p.2')

    def test_context_reference_ids_match_the_serialized_excerpts(self):
        docs = [doc('First passage', source='one.pdf', page=0),
                doc('Second passage', source='two.txt')]
        context = format_context(docs)
        for citation in build_citations(docs):
            self.assertIn(f"[{citation['id']}] {citation['source']}", context)
            self.assertIn(citation['text'], context)
        self.assertNotIn('p.?', format_sources(docs))

    def test_rows_page_labels_and_urls_are_not_confused(self):
        citations = build_citations([
            doc('Table row', source='data.csv', row=7),
            doc('Preface', source='book.pdf', page=3, page_label='iv'),
            doc('Website', source='Page', url='https://example.com/article'),
            doc('Unsafe URL', source='Page', url='javascript:alert(1)'),
        ])
        self.assertIsNone(citations[0]['page'])
        self.assertEqual(citations[0]['row'], 7)
        self.assertEqual(citations[1]['page'], 4)
        self.assertEqual(citations[1]['page_label'], 'iv')
        self.assertEqual(citations[2]['url'], 'https://example.com/article')
        self.assertIsNone(citations[3]['url'])

    def test_legacy_documents_without_metadata_have_a_readable_label(self):
        self.assertEqual(format_sources([doc('text')]), 'Unknown source')
        self.assertEqual(build_citations([]), [])


if __name__ == '__main__':
    unittest.main()
