"""Exercise real document ingestion and provider generation using temporary synthetic data."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_pdf(path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_ref = writer._add_object(font)
    pages = [
        ['Synthetic test guide - gardening notes.'] +
        [f'Garden section {i}: Soil, watering, sunlight, plants and seasonal care.' for i in range(25)],
        ['Synthetic test guide - Project Aurora.',
         'Project Aurora launched on 12 March 2025.',
         'The launch coordinator was Elena Novak.',
         'The launch took place in Bratislava.'] +
        [f'Aurora preparation {i}: The team reviewed documentation before the launch.' for i in range(22)],
        ['Synthetic test guide - library opening hours.'] +
        [f'Library section {i}: Readers can borrow books and consult the public catalogue.' for i in range(25)],
    ]
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref})})
        content = DecodedStreamObject()
        commands = ['BT /F1 11 Tf 40 750 Td']
        for line in lines:
            commands.append(f'({line}) Tj 0 -18 Td')
        commands.append('ET')
        content.set_data('\n'.join(commands).encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(content)
    writer.write(path)


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    if os.getenv('LLM_PROVIDER', 'groq') == 'groq':
        from groq import Groq
        available = Groq().models.list()
        print('AVAILABLE_MODELS', [model.id for model in available.data if model.active], flush=True)
    from fastapi.testclient import TestClient
    import server
    from rag import ingestor, retriever, parents

    with tempfile.TemporaryDirectory(prefix='rag-live-') as directory:
        root = Path(directory)
        data = root / 'data'
        server.CHROMA_BASE = data
        server.SESSIONS_FILE = data / 'sessions.json'
        for module in [ingestor, retriever, parents]:
            module.CHROMA_BASE_DIR = str(data)
        pdf = root / 'guide.pdf'
        make_pdf(pdf)
        with TestClient(server.app) as client:
            session = client.post('/api/sessions', json={'name': 'Live integration check'}).json()
            session_id = session['id']
            with pdf.open('rb') as handle:
                uploaded = client.post(f'/api/upload?session_id={session_id}',
                                       files={'file': ('guide.pdf', handle, 'application/pdf')})
            if uploaded.status_code != 200:
                raise RuntimeError(f'Upload failed: HTTP {uploaded.status_code} {uploaded.text}')
            print('UPLOAD', uploaded.json(), flush=True)
            question = 'On what date did Project Aurora launch? Cite the supporting passage.'
            response = client.post('/api/chat/stream', json={'session_id': session_id, 'question': question})
            events = [json.loads(frame[6:]) for frame in response.text.strip().split('\n\n')]
            errors = [event for event in events if event['type'] == 'error']
            if errors:
                raise RuntimeError(f'Stream failed: {errors}')
            answer = ''.join(event['content'] for event in events if event['type'] == 'token')
            final = next(event for event in events if event['type'] == 'done')
            assert '2025' in answer and ('12' in answer or 'March 12' in answer), answer
            assert any(citation['page'] == 2 and '12 March 2025' in citation['text']
                       for citation in final['citations']), final
            print('ANSWER', answer, flush=True)
            print('CITATIONS', [{key: citation[key] for key in ['id', 'source', 'page']}
                                for citation in final['citations']], flush=True)
            result = client.post('/api/chat', json={'session_id': session_id,
                                 'question': 'Who coordinated the Project Aurora launch?'})
            assert result.status_code == 200, result.text
            assert 'Elena' in result.json()['answer'], result.json()
            assert result.json()['citations'], result.json()
            print('NONSTREAM', result.json()['answer'], flush=True)

            async def stop_stream():
                response = await server.chat_stream(server.ChatRequest(session_id=session_id,
                    question='Explain the Project Aurora launch in several paragraphs.'))
                received_token = False
                async for frame in response.body_iterator:
                    event = json.loads(frame[6:])
                    if event['type'] == 'error':
                        raise RuntimeError(str(event))
                    if event['type'] == 'token' and event['content']:
                        received_token = True
                        break
                await response.body_iterator.aclose()
                assert received_token
                acquired = 0
                try:
                    for _ in range(2):
                        assert server._chat_slots.acquire(blocking=False)
                        acquired += 1
                    assert not server._chat_slots.acquire(blocking=False)
                finally:
                    for _ in range(acquired):
                        server._chat_slots.release()

            asyncio.run(stop_stream())
            print('STOP: token received, stream closed, capacity released', flush=True)
            assert client.get('/api/sessions').json()['sessions'][0]['documents'] == ['guide.pdf']
            print('LIVE API SCENARIO PASSED', flush=True)


if __name__ == '__main__':
    main()
