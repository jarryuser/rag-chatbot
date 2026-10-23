"""Exercise duplicate detection and rollback against real ChromaDB in a temporary directory."""

import json
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from rag import ingestor, retriever, parents, indexing
    from rag.storage import write_json

    with tempfile.TemporaryDirectory(prefix='rag-documents-') as temporary:
        root = Path(temporary)
        data = root / 'data'
        for module in [ingestor, retriever, parents]:
            module.CHROMA_BASE_DIR = str(data)
        path = root / 'guide.txt'
        path.write_text('Project Aurora launched on 12 March 2025. Coordinator: Elena Novak.')
        old = ingestor.ingest(str(path), session_id='default', return_result=True)
        self_store = retriever._load_vectorstore('default')
        count = self_store._collection.count()
        self_dir = data / 'default'
        before = self_store.get(include=['documents', 'metadatas'])
        parent_before = parents.load_parents('default')
        assert ingestor.ingest(str(path), session_id='default', return_result=True).status == 'skipped'
        assert ingestor.ingest(str(path), display_name='copy.txt', return_result=True).status == 'skipped'
        assert self_store._collection.count() == count
        path.write_text('Project Aurora launched on 20 August 2026. Coordinator: Tomas Urban.')
        try:
            ingestor.ingest(str(path), return_result=True)
        except indexing.DocumentConflict:
            pass
        else:
            raise AssertionError('Changed document did not require confirmation')
        original = ingestor.Chroma.add_documents

        def partial_failure(store, documents, ids):
            original(store, documents[:1], ids=ids[:1])
            raise RuntimeError('Injected partial write failure')

        with patch.object(ingestor.Chroma, 'add_documents', partial_failure):
            try:
                ingestor.ingest(str(path), replace=True, return_result=True)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Injected failure was ignored')
        assert self_store.get(include=['documents', 'metadatas']) == before
        assert parents.load_parents('default') == parent_before

        def interrupt(path, value):
            if path.name == 'documents.json':
                raise KeyboardInterrupt()
            write_json(path, value)

        with patch.object(indexing, 'write_json', side_effect=interrupt):
            try:
                ingestor.ingest(str(path), replace=True, return_result=True)
            except KeyboardInterrupt:
                pass
        assert (self_dir / 'index-journal.json').exists()
        recovered = retriever._load_vectorstore('default')
        assert not (self_dir / 'index-journal.json').exists()
        assert recovered.get(include=['documents', 'metadatas']) == before
        assert parents.load_parents('default') == parent_before
        replaced = ingestor.ingest(str(path), replace=True, return_result=True)
        assert replaced.document_id == old.document_id
        assert replaced.status == 'replaced'
        assert self_store._collection.count() == count
        assert all('2025' not in text for text in self_store.get()['documents'])
        ingestor.remove_document('default', 'guide.txt')
        assert self_store._collection.count() == 0
        assert indexing.document_names(self_dir) == []
        assert parents.load_parents('default') == {}
        from langchain_core.documents import Document
        legacy_id = str(uuid.uuid4())
        legacy_store, legacy_dir = ingestor._store(legacy_id)
        legacy_store.add_documents([
            Document(page_content='First page', metadata={'source': 'Same title', 'url': 'https://example.com/one'}),
            Document(page_content='Second page', metadata={'source': 'Same title', 'url': 'https://example.com/two'}),
        ])
        indexing.replace_document(legacy_store, legacy_dir, 'url:https://example.com/one', 'Same title',
                                  'new', [Document(page_content='Updated page', metadata={'url': 'https://example.com/one'})],
                                  {'new': {'text': 'Updated page', 'metadata': {'url': 'https://example.com/one'}}},
                                  replace=True)
        assert legacy_store.get(where={'url': 'https://example.com/two'})['documents'] == ['Second page']
        assert legacy_store._collection.count() == 2
        print(json.dumps({'duplicates': 'passed', 'explicit_replacement': 'passed',
                          'partial_write_rollback': 'passed', 'interruption_recovery': 'passed',
                          'stable_document_id': 'passed', 'delete_cleanup': 'passed',
                          'legacy_url_isolation': 'passed'}, indent=2))


if __name__ == '__main__':
    main()
