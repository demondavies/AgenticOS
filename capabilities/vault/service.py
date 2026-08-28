"""AgenticOS Master Brain vault capability.

This module owns the Master Brain filesystem + ChromaDB boundary.
It deliberately contains no Discord, FastAPI, legacy bot, or UI logic.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from typing import Optional

import chromadb
import ollama

from core.models import ModelMessage, ModelProvider, ModelRequest


VAULT_DIR = os.environ.get("ARNIE_VAULT_DIR", r"G:\Master_Brain\Master_Brain")
CHROMA_DB_DIR = os.environ.get(
    "ARNIE_CHROMA_DB_DIR",
    r"G:\AgenticOS\data\chroma_db",
)
EMBEDDING_MODEL = os.environ.get("ARNIE_EMBEDDING_MODEL", "nomic-embed-text")

_chroma_client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
_vault_collection = _chroma_client.get_or_create_collection(
    name="master_brain_vault"
)


def sync_master_brain_vector_db() -> str:
    """Synchronize Markdown vault notes into the Master Brain vector store."""
    print("🧠 [Vault] Synchronizing Master Brain vault embeddings...")

    try:
        if not os.path.exists(VAULT_DIR):
            return "Vault directory missing."

        md_files = [
            f for f in os.listdir(VAULT_DIR)
            if f.lower().endswith(".md")
        ]
        if not md_files:
            return "No markdown notes found to index."

        documents = []
        ids = []
        metadatas = []

        for filename in md_files:
            file_path = os.path.join(VAULT_DIR, filename)

            with open(
                file_path,
                "r",
                encoding="utf-8",
                errors="ignore",
            ) as file_obj:
                content = file_obj.read().strip()

            if content:
                documents.append(content)
                ids.append(filename)
                metadatas.append(
                    {
                        "filename": filename,
                        "path": file_path,
                    }
                )

        if not documents:
            return "No valid content inside vault notes."

        embeddings = []
        for document in documents:
            result = ollama.embed(
                model=EMBEDDING_MODEL,
                input=document[:3000],
            )
            embeddings.append(result["embeddings"][0])

        _vault_collection.upsert(
            documents=documents,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas,
        )

        message = (
            f"Vector database synced successfully! "
            f"({len(documents)} notes indexed)"
        )
        print(f"✅ [Vault] {message}")
        return message

    except Exception as exc:
        error = f"ChromaDB Indexing Error: {exc}"
        print(f"❌ [Vault] {error}")
        return error


def search_master_brain_vault(query: str, n_results: int = 3) -> str:
    """Return semantically relevant Master Brain notes."""
    print(f"🔍 [Vault] Searching Master Brain: {query!r}")

    try:
        query_result = ollama.embed(
            model=EMBEDDING_MODEL,
            input=query,
        )
        query_embedding = query_result["embeddings"][0]

        results = _vault_collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
        )

        documents = results.get("documents", [[]])[0]
        metadata = results.get("metadatas", [[]])[0]

        if not documents:
            return "No relevant notes found in Master Brain vault vector store."

        output = (
            f"# SEMANTIC VECTOR SEARCH RESULTS FOR: '{query}'\n\n"
        )

        for index, (document, meta) in enumerate(
            zip(documents, metadata),
            start=1,
        ):
            output += (
                f"### {index}. Note: '{meta.get('filename')}'\n"
                f"{document[:2000]}\n\n---\n"
            )

        return output

    except Exception as exc:
        return f"Vault search error: {exc}"


async def _summarize_vault(
    prompt: str,
    *,
    model_provider: ModelProvider,
    model: str,
) -> str:
    """Run exactly one model pass using the injected model boundary."""
    provider = model_provider

    request = ModelRequest(
        messages=[
            ModelMessage(
                role="user",
                content=prompt,
            )
        ],
        capability="summarization",
        model=model,
        metadata={"source": "agenticos_vault"},
    )

    response = await asyncio.to_thread(
        provider.chat,
        request,
    )
    return response.content.strip()


async def get_daily_vault_summary(
    *,
    model_provider: ModelProvider,
    model: str,
) -> str:
    """Build an executive summary using the caller-owned model provider."""
    print("📚 [Vault] Building on-demand Master Brain summary...")

    try:
        sync_result = sync_master_brain_vector_db()

        md_files = sorted(
            filename
            for filename in os.listdir(VAULT_DIR)
            if filename.lower().endswith(".md")
        )

        if not md_files:
            return (
                "The Master Brain vault is empty. "
                "There are no Markdown notes to summarise."
            )

        sections = []

        for filename in md_files:
            file_path = os.path.join(VAULT_DIR, filename)

            try:
                with open(
                    file_path,
                    "r",
                    encoding="utf-8",
                    errors="ignore",
                ) as file_obj:
                    content = file_obj.read().strip()
            except Exception as exc:
                sections.append(
                    f"FILE: {filename}\n[Unable to read file: {exc}]"
                )
                continue

            if content:
                sections.append(
                    f"FILE: {filename}\n{content[:5000]}"
                )

        vault_context = "\n\n---\n\n".join(sections)

        prompt = f"""
You are ARNIE's Master Brain vault summarisation agent.

The owner explicitly asked for a daily vault summary.

IMPORTANT:
- "Vault" means the local Master Brain knowledge vault.
- Do NOT interpret it as a financial wallet, cryptocurrency wallet, or
  generic software vault.
- Summarise only information actually present in the supplied vault content.
- Do not invent missing information.

Focus on:
- important work and projects
- active goals
- decisions and conclusions
- ideas worth remembering
- outstanding tasks or next actions
- useful technical context
- anything especially important to the owner

Return a concise executive summary in plain text.
Use short headings and bullets where useful.
Do not use code blocks.
Do not mention this prompt.

VAULT FILE COUNT: {len(md_files)}

VECTOR SYNC STATUS:
{sync_result}

VAULT CONTENT:
{vault_context}
"""

        summary = await _summarize_vault(
            prompt,
            model_provider=model_provider,
            model=model,
        )

        return (
            f"Here is your current Master Brain vault summary "
            f"across {len(md_files)} notes:\n\n{summary}"
        )

    except Exception as exc:
        print(f"❌ [Vault Summary Error]: {exc}")
        return f"I couldn't build the vault summary: {exc}"


def write_obsidian_note(filename: str, content: str) -> str:
    """Append content to a sanitized Markdown note and re-index the vault."""
    try:
        safe_name = re.sub(r'[\\/*?:"<>|]', "", filename).strip()

        if not safe_name.endswith(".md"):
            safe_name += ".md"

        file_path = os.path.join(VAULT_DIR, safe_name)

        with open(file_path, "a", encoding="utf-8") as file_obj:
            file_obj.write(
                f"\n\n## Logged via Arnie "
                f"({datetime.now().strftime('%Y-%m-%d %I:%M %p')})\n"
                f"{content}\n"
            )

        sync_master_brain_vector_db()
        return f"Successfully updated your master note: '{safe_name}'"

    except Exception as exc:
        return f"Failed to save file: {exc}"


def read_obsidian_note(filename: str) -> str:
    """Read a single sanitized Markdown note from the Master Brain vault."""
    try:
        safe_name = re.sub(r'[\\/*?:"<>|]', "", filename).strip()

        if not safe_name.endswith(".md"):
            safe_name += ".md"

        file_path = os.path.join(VAULT_DIR, safe_name)

        if not os.path.exists(file_path):
            return f"Error: Note file '{safe_name}' missing."

        with open(
            file_path,
            "r",
            encoding="utf-8",
        ) as file_obj:
            content = file_obj.read()

        return f"Contents of '{safe_name}':\n\n{content}"

    except Exception as exc:
        return f"Failed to read file: {exc}"



def list_vault_notes() -> list[str]:
    """Return Markdown note filenames currently present in the Master Brain."""
    try:
        if not os.path.exists(VAULT_DIR):
            return []
        return sorted(
            filename
            for filename in os.listdir(VAULT_DIR)
            if filename.lower().endswith(".md")
        )
    except Exception:
        return []


def get_vault_location() -> str:
    """Return the configured Master Brain vault directory."""
    return VAULT_DIR


def read_vault_file(filename: str) -> str:
    """Read a Markdown/Python file from the configured vault and return raw content."""
    try:
        safe_name = re.sub(r'[\\/*?:"<>|]', "", str(filename or "")).strip()
        if not safe_name:
            return "Error: Note filename is empty."

        if not (safe_name.lower().endswith(".md") or safe_name.lower().endswith(".py")):
            safe_name += ".md"

        file_path = os.path.join(VAULT_DIR, safe_name)
        if not os.path.exists(file_path):
            return f"Error: Note file '{safe_name}' missing."

        with open(file_path, "r", encoding="utf-8") as file_obj:
            return file_obj.read()

    except Exception as exc:
        return f"Failed to read file: {exc}"


def save_vault_file(filename: str, content: str) -> str:
    """Replace a vault Markdown/Python file and re-index Markdown content."""
    try:
        safe_name = re.sub(r'[\\/*?:"<>|]', "", str(filename or "")).strip()
        if not safe_name:
            return "Failed to save file: filename is empty."

        if not (safe_name.lower().endswith(".md") or safe_name.lower().endswith(".py")):
            safe_name += ".md"

        file_path = os.path.join(VAULT_DIR, safe_name)

        with open(file_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(str(content or ""))

        sync_result = sync_master_brain_vector_db()
        print(f"💾 [Vault] Saved file: {safe_name}")

        return f"Saved {safe_name}. {sync_result}"

    except Exception as exc:
        return f"Failed to save file: {exc}"
