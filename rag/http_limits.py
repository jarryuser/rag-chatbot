"""Reject oversized API requests before buffering their complete bodies."""

from fastapi import HTTPException
from starlette.responses import JSONResponse

from .limits import MAX_UPLOAD_BYTES


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/'):
            return await self.app(scope, receive, send)
        limit = MAX_UPLOAD_BYTES + 1024 * 1024 if scope['path'] == '/api/upload' else 160 * 1024
        headers = dict(scope.get('headers', []))
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await JSONResponse({'detail': 'Invalid Content-Length.'}, status_code=400)(scope, receive, send)
        if length > limit:
            return await JSONResponse({'detail': 'Request body is too large.'}, status_code=413)(scope, receive, send)
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            if message['type'] == 'http.request':
                size += len(message.get('body', b''))
                if size > limit:
                    raise HTTPException(status_code=413, detail='Request body is too large.')
            return message

        await self.app(scope, limited_receive, send)
