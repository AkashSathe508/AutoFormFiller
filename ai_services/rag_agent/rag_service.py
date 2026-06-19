"""RAG Agent Service.

Provides intelligent contextual guidance by performing semantic search
over the rag_chunks table and synthesizing answers using a local LLM.
"""

import logging
import httpx
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class RagService:
    def __init__(
        self,
        db: AsyncSession,
        embedding_model_name: str = "intfloat/multilingual-e5-small",
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = "qwen2.5:7b-instruct-q4_K_M",
        ollama_timeout: int = 60,
    ):
        self.db = db
        self.embedding_model_name = embedding_model_name
        self.ollama_host = ollama_host
        self.ollama_model = ollama_model
        self.ollama_timeout = ollama_timeout
        self._embed_model = None

    async def ask(self, question: str, scheme_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Answer a question using RAG.
        Returns: { "answer": str, "sources": [ {id, chunk_text, source_url} ] }
        """
        # 1. Embed the question
        query_vec = self._embed_question(question)
        if not query_vec:
            return {
                "answer": "I am currently unable to process your question due to an embedding service failure.",
                "sources": []
            }

        # 2. Retrieve context
        chunks = await self._retrieve_context(query_vec, limit=4, scheme_id=scheme_id)
        
        if not chunks:
            return {
                "answer": "I don't have verified information on this in my knowledge base. Please check the official source.",
                "sources": []
            }

        # 3. Generate answer
        answer = await self._generate_answer(question, chunks)

        # 4. Format sources
        sources = [
            {
                "id": str(c["id"]),
                "chunk_text": c["chunk_text"],
                "source_url": c["source_url"] or ""
            }
            for c in chunks
        ]

        return {
            "answer": answer,
            "sources": sources
        }

    def _embed_question(self, question: str) -> Optional[List[float]]:
        try:
            from sentence_transformers import SentenceTransformer
            if self._embed_model is None:
                logger.debug("Loading embedding model: %s", self.embedding_model_name)
                self._embed_model = SentenceTransformer(self.embedding_model_name)

            query_vec = self._embed_model.encode(
                f"query: {question}",
                normalize_embeddings=True,
            )
            return query_vec.tolist()
        except Exception as e:
            logger.error("Failed to embed RAG question: %s", e)
            return None

    async def _retrieve_context(self, query_vec: List[float], limit: int = 4, scheme_id: Optional[str] = None) -> List[Dict[str, Any]]:
        vec_str = "[" + ",".join(f"{v:.6f}" for v in query_vec) + "]"
        
        # Build query
        query = """
            SELECT id, chunk_text, source_url,
                   1 - (embedding <=> CAST(:vec AS vector)) AS cosine_sim
            FROM rag_chunks
        """
        params = {"vec": vec_str, "limit": limit}
        
        if scheme_id:
            query += " WHERE scheme_id = :scheme_id OR scheme_id IS NULL"
            params["scheme_id"] = scheme_id
            
        query += """
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :limit
        """
        
        try:
            result_proxy = await self.db.execute(text(query), params)
            result = result_proxy.fetchall()
            
            # Filter by a reasonable similarity threshold (e.g. 0.75) to avoid retrieving completely unrelated chunks
            chunks = []
            for row in result:
                if row.cosine_sim >= 0.75:
                    chunks.append({
                        "id": row.id,
                        "chunk_text": row.chunk_text,
                        "source_url": row.source_url,
                        "score": row.cosine_sim
                    })
            return chunks
        except Exception as e:
            logger.error("Failed to retrieve RAG context: %s", e)
            return []

    async def _generate_answer(self, question: str, chunks: List[Dict[str, Any]]) -> str:
        context_str = "\n\n".join([f"[Source {i+1}]: {c['chunk_text']}" for i, c in enumerate(chunks)])
        
        prompt = f"""
SYSTEM: You are a helpful assistant for Indian government form filling.
Answer the user's question ONLY using the provided context chunks.
If the context does not contain the answer, say "I don't have verified information on this — please check the official source" and do not guess.
Cite which source you used using [Source X] notation.

CONTEXT CHUNKS:
{context_str}

USER QUESTION: {question}

ANSWER:
"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.0},
                    },
                    timeout=self.ollama_timeout,
                )
                response.raise_for_status()
                return response.json().get("response", "").strip()
        except Exception as e:
            logger.error("LLM generation failed for RAG: %s", e)
            return "I am currently unable to generate an answer. Please try again later."
