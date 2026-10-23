"""Public entry points; model dependencies load only when needed."""


def ingest(file_path, display_name=None, session_id="default", *, replace=False, return_result=False):
    from .ingestor import ingest as run
    return run(file_path, display_name=display_name, session_id=session_id,
               replace=replace, return_result=return_result)


def ingest_url(url, session_id="default", *, replace=False, return_result=False):
    from .ingestor import ingest_url as run
    return run(url, session_id=session_id, replace=replace, return_result=return_result)


def get_answer(question, session_id="default", history=None):
    from .retriever import get_answer as run
    return run(question, session_id=session_id, history=history)


__all__ = ["ingest", "ingest_url", "get_answer"]
