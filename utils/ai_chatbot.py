import os
import re


MODEL_OPTIONS = {
    "Amazon Nova Lite": "amazon.nova-lite-v1:0",
    "Amazon Nova Pro": "amazon.nova-pro-v1:0",
    "Claude 3.5 Sonnet": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "Claude 3 Haiku": "anthropic.claude-3-haiku-20240307-v1:0",
}


def get_default_region():
    return (
        os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def get_default_model_id():
    return os.getenv("BEDROCK_MODEL_ID") or MODEL_OPTIONS["Amazon Nova Lite"]


def _split_text_into_page_chunks(row, chunk_size=1200):
    extracted_text = str(row.get("extracted_text", "") or "").strip()
    if not extracted_text:
        return [
            {
                "text": "No extracted text stored for this document.",
                "page": "",
                "row": row,
            }
        ]

    page_sections = re.split(r"\n?--- Page (\d+) ---\n?", extracted_text)
    chunks = []
    if len(page_sections) > 1:
        for index in range(1, len(page_sections), 2):
            page_number = page_sections[index]
            page_text = page_sections[index + 1].strip()
            for start in range(0, len(page_text), chunk_size):
                chunk_text = page_text[start:start + chunk_size].strip()
                if chunk_text:
                    chunks.append({"text": chunk_text, "page": page_number, "row": row})
    else:
        for start in range(0, len(extracted_text), chunk_size):
            chunk_text = extracted_text[start:start + chunk_size].strip()
            if chunk_text:
                chunks.append({"text": chunk_text, "page": "", "row": row})

    return chunks


def retrieve_source_chunks(documents_df, question, max_sources=6):
    if documents_df.empty:
        return []

    query_terms = {
        term
        for term in re.findall(r"[a-zA-Z0-9]{3,}", question.lower())
        if term not in {"the", "and", "for", "with", "that", "this"}
    }

    scored_chunks = []
    for _, row in documents_df.fillna("").iterrows():
        row_text = " ".join(
            str(row.get(column, ""))
            for column in [
                "doc_id",
                "product_name",
                "document_name",
                "document_type",
                "version",
                "upload_date",
            ]
        )
        for chunk in _split_text_into_page_chunks(row):
            searchable = f"{row_text} {chunk['text']}".lower()
            score = sum(searchable.count(term) for term in query_terms)
            if score > 0 or not query_terms:
                scored_chunks.append((score, chunk))

    if not scored_chunks:
        for _, row in documents_df.fillna("").iterrows():
            for chunk in _split_text_into_page_chunks(row)[:1]:
                scored_chunks.append((0, chunk))

    scored_chunks.sort(key=lambda item: item[0], reverse=True)

    sources = []
    for source_index, (_, chunk) in enumerate(scored_chunks[:max_sources], start=1):
        row = chunk["row"]
        page = chunk["page"]
        citation = f"S{source_index}"
        source_label = (
            f"[{citation}] {row.get('document_name', '')}"
            f"{f', page {page}' if page else ''}"
            f" | Product: {row.get('product_name', '')}"
        )
        sources.append(
            {
                "citation": citation,
                "source_label": source_label,
                "doc_id": row.get("doc_id", ""),
                "document_name": row.get("document_name", ""),
                "product_name": row.get("product_name", ""),
                "page": page,
                "text": chunk["text"],
            }
        )

    return sources


def build_document_context(documents_df, question, max_chars=9000):
    sources = retrieve_source_chunks(documents_df, question)
    if not sources:
        return "No uploaded documents are available yet."

    context_blocks = []
    remaining_chars = max_chars
    for source in sources:
        block = "\n".join(
            [
                source["source_label"],
                source["text"],
            ]
        )

        if remaining_chars <= 0:
            break

        context_blocks.append(block[:remaining_chars])
        remaining_chars -= len(context_blocks[-1])

    return "\n\n---\n\n".join(context_blocks)


def _format_response_content(content):
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()

    return str(content)


def ask_bedrock_chatbot(question, documents_df, chat_history, model_id, region_name):
    try:
        from langchain_aws import ChatBedrockConverse
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    except ImportError as exc:
        return {
            "success": False,
            "answer": (
                "LangChain AWS dependencies are not installed. Install "
                "`boto3`, `langchain-core`, and `langchain-aws` to enable Bedrock chat."
            ),
            "error": str(exc),
        }

    sources = retrieve_source_chunks(documents_df, question)
    document_context = build_document_context(documents_df, question)
    system_prompt = f"""
You are a regulatory compliance assistant for a pharma document tracker.
Answer using the provided product and document context. Be concise and practical.
If the answer is not present in the context, say what is missing and suggest the next compliance action.
Do not invent regulatory facts, approvals, dates, SOP contents, or document statuses.
When you use document context, cite the relevant source IDs exactly like [S1] or [S2].

Document context:
{document_context}
""".strip()

    messages = [SystemMessage(content=system_prompt)]
    for message in chat_history[-8:]:
        if message["role"] == "user":
            messages.append(HumanMessage(content=message["content"]))
        elif message["role"] == "assistant":
            messages.append(AIMessage(content=message["content"]))
    messages.append(HumanMessage(content=question))

    try:
        llm = ChatBedrockConverse(
            model_id=model_id,
            region_name=region_name,
            temperature=0.2,
            max_tokens=1200,
        )
        response = llm.invoke(messages)
        return {
            "success": True,
            "answer": _format_response_content(response.content),
            "error": "",
            "sources": sources,
        }
    except Exception as exc:
        return {
            "success": False,
            "answer": (
                "Could not reach Amazon Bedrock. Check AWS credentials, region, "
                "Bedrock model access, and the selected model ID."
            ),
            "error": str(exc),
            "sources": sources,
        }
