import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rag import indexing
from rag.limits import ResourceLimitError
from rag.storage import write_json


class MemoryStore:
    def __init__(self):
        self.rows = {}
        self._collection = self
        self.fail_add = False

    def count(self):
        return len(self.rows)

    def get(self, where=None, include=None):
        matches = [(key, value) for key, value in self.rows.items()
                   if not where or all(all(value['metadata'].get(k) == v for k, v in term.items())
                                     for term in where.get('$and', [where]))]
        return {'ids': [key for key, _ in matches], 'documents': [v['text'] for _, v in matches],
                'metadatas': [copy.deepcopy(v['metadata']) for _, v in matches],
                'embeddings': [v['embedding'] for _, v in matches]}

    def delete(self, ids):
        for key in ids:
            self.rows.pop(key, None)

    def upsert(self, ids, documents, metadatas, embeddings):
        for key, text, metadata, embedding in zip(ids, documents, metadatas, embeddings):
            self.rows[key] = {'text': text, 'metadata': copy.deepcopy(metadata), 'embedding': embedding}

    def add_documents(self, documents, ids):
        for doc, key in zip(documents, ids):
            self.rows[key] = {'text': doc.page_content, 'metadata': copy.deepcopy(doc.metadata), 'embedding': [0.1, 0.2]}
            if self.fail_add:
                raise RuntimeError('Embedding or vector write failed')


class IndexingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = MemoryStore()

    def tearDown(self):
        self.temp.cleanup()

    def ingest(self, text='old text', fingerprint='old', source='guide.txt', key=None, replace=False):
        parent_id = 'parent-' + fingerprint
        child = SimpleNamespace(page_content=text, metadata={'parent_id': parent_id, 'source': source})
        parents = {parent_id: {'text': text, 'metadata': {'source': source}}}
        return indexing.replace_document(self.store, self.directory, key or 'file:' + source,
                                          source, fingerprint, [child], parents, replace=replace)

    def snapshot(self):
        return (copy.deepcopy(self.store.rows),
                json.loads((self.directory / 'parents.json').read_text()),
                json.loads((self.directory / 'documents.json').read_text()))

    def test_duplicate_and_renamed_duplicate_do_not_add_vectors(self):
        result = self.ingest()
        before = self.snapshot()
        self.assertEqual(self.ingest().status, 'skipped')
        renamed = self.ingest(source='renamed.txt')
        self.assertEqual(renamed.status, 'skipped')
        self.assertEqual(renamed.source, 'guide.txt')
        self.assertEqual(renamed.document_id, result.document_id)
        self.assertEqual(self.snapshot(), before)

    def test_changed_document_requires_explicit_replacement(self):
        self.ingest()
        before = self.snapshot()
        with self.assertRaises(indexing.DocumentConflict):
            self.ingest('new text', 'new')
        self.assertEqual(self.snapshot(), before)

    def test_replacement_preserves_id_and_removes_old_children_and_parents(self):
        old = self.ingest()
        new = self.ingest('new text', 'new', replace=True)
        self.assertEqual(new.document_id, old.document_id)
        self.assertEqual(new.status, 'replaced')
        self.assertEqual([row['text'] for row in self.store.rows.values()], ['new text'])
        parents = json.loads((self.directory / 'parents.json').read_text())
        self.assertEqual(list(parents), ['parent-new'])
        self.assertFalse((self.directory / 'index-journal.json').exists())

    def test_partial_vector_failure_restores_everything(self):
        self.ingest()
        before = self.snapshot()
        self.store.fail_add = True
        with self.assertRaises(RuntimeError):
            self.ingest('new text', 'new', replace=True)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.directory / 'index-journal.json').exists())

    def test_metadata_failure_rolls_back_vectors_and_metadata(self):
        self.ingest()
        before = self.snapshot()
        failed = False

        def fail_once(path, value):
            nonlocal failed
            if path.name == 'documents.json' and not failed:
                failed = True
                raise OSError('disk write failed')
            write_json(path, value)

        with patch.object(indexing, 'write_json', side_effect=fail_once), self.assertRaises(OSError):
            self.ingest('new text', 'new', replace=True)
        self.assertEqual(self.snapshot(), before)

    def test_interrupted_update_is_recovered_before_next_operation(self):
        self.ingest()
        before = self.snapshot()

        def interrupt(path, value):
            if path.name == 'documents.json':
                raise KeyboardInterrupt()
            write_json(path, value)

        with patch.object(indexing, 'write_json', side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.ingest('new text', 'new', replace=True)
        self.assertTrue((self.directory / 'index-journal.json').exists())
        self.assertEqual(indexing.document_names(self.directory), ['guide.txt'])
        indexing.recover_index(self.store, self.directory)
        self.assertEqual(self.snapshot(), before)

    def test_failed_rollback_keeps_journal_for_retry(self):
        self.ingest()
        before = self.snapshot()
        self.store.fail_add = True
        with patch.object(self.store, 'upsert', side_effect=OSError), self.assertRaises(OSError):
            self.ingest('new text', 'new', replace=True)
        self.assertTrue((self.directory / 'index-journal.json').exists())
        indexing.recover_index(self.store, self.directory)
        self.assertEqual(self.snapshot(), before)

    def test_replacement_and_duplicates_work_at_capacity(self):
        self.ingest()
        with patch.object(indexing, 'MAX_DOCUMENTS_PER_SESSION', 1), patch.object(indexing, 'MAX_CHUNKS_PER_SESSION', 1):
            self.assertEqual(self.ingest().status, 'skipped')
            self.assertEqual(self.ingest('new', 'new', replace=True).status, 'replaced')
            with self.assertRaises(ResourceLimitError):
                self.ingest('other', 'other', source='other.txt')

    def test_urls_with_matching_titles_keep_separate_sources(self):
        self.ingest(key='url:https://example.com/one', source='Same title')
        other = self.ingest('other', 'other', key='url:https://example.com/two', source='Same title')
        self.assertNotEqual(other.source, 'Same title')
        self.assertEqual(self.store.count(), 2)
        indexing.delete_document(self.store, self.directory, other.source)
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(indexing.document_names(self.directory), ['Same title'])

    def test_replacing_legacy_url_does_not_delete_another_page_with_the_same_title(self):
        self.store.upsert(['one', 'two'], ['first URL', 'second URL'],
                          [{'source': 'Same title', 'url': 'https://example.com/one'},
                           {'source': 'Same title', 'url': 'https://example.com/two'}], [[0.1, 0.2]] * 2)
        result = self.ingest('updated', 'new', source='Same title',
                             key='url:https://example.com/one', replace=True)
        self.assertIn('two', self.store.rows)
        self.assertNotIn('one', self.store.rows)
        self.assertNotEqual(result.source, 'Same title')
        self.assertEqual(self.store.count(), 2)

    def test_legacy_source_can_be_replaced_without_leaving_old_chunks(self):
        self.store.upsert(['legacy'], ['legacy text'], [{'source': 'guide.txt'}], [[0.1, 0.2]])
        write_json(self.directory / 'parents.json', {'legacy-parent': {'text': 'legacy', 'metadata': {'source': 'guide.txt'}}})
        self.assertEqual(self.ingest('new', 'new', replace=True).status, 'replaced')
        self.assertNotIn('legacy', self.store.rows)
        self.assertNotIn('legacy-parent', json.loads((self.directory / 'parents.json').read_text()))


if __name__ == '__main__':
    unittest.main()
