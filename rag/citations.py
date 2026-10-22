"""Serializable snapshots of the passages supplied to the language model."""


def build_citations(docs: list) -> list[dict]:
    citations = []
    for index, doc in enumerate(docs, start=1):
        metadata = doc.metadata
        page = metadata.get("page")
        row = metadata.get("row")
        url = metadata.get("url")
        citations.append({
            "id": index,
            "source": str(metadata.get("source") or "Unknown source"),
            "page": int(page) + 1 if isinstance(page, int) and page >= 0 else None,
            "page_label": str(metadata["page_label"]) if metadata.get("page_label") else None,
            "row": int(row) if isinstance(row, int) else None,
            "url": url if isinstance(url, str) and url.startswith(("https://", "http://")) else None,
            "text": doc.page_content,
        })
    return citations


def citation_label(citation: dict) -> str:
    label = citation["source"]
    if citation.get("page") is not None:
        label += f" p.{citation.get('page_label') or citation['page']}"
    elif citation.get("row") is not None:
        label += f" row {citation['row']}"
    return label


def format_context(docs: list) -> str:
    return "\n\n---\n\n".join(
        f"[{citation['id']}] {citation_label(citation)}\n{citation['text']}"
        for citation in build_citations(docs)
    )


def format_sources(docs: list) -> str:
    return ", ".join(dict.fromkeys(citation_label(citation) for citation in build_citations(docs)))
