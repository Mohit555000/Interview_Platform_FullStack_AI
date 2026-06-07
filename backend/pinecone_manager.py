import os
import uuid
from typing import Dict, Any, List
from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings

_INDEX_NAME = "interviewai"
_DIMENSION = 1536
_METRIC = "cosine"


class PineconeManager:
    def __init__(self, openai_api_key: str = None):
        self.pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        if _INDEX_NAME not in self.pc.list_indexes().names():
            self.pc.create_index(
                name=_INDEX_NAME,
                dimension=_DIMENSION,
                metric=_METRIC,
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
        self.index = self.pc.Index(_INDEX_NAME)
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=openai_api_key or os.getenv("OPENAI_API_KEY"),
        )

    def _upsert_batch(self, namespace: str, vectors: list, batch_size: int = 100):
        for i in range(0, len(vectors), batch_size):
            self.index.upsert(vectors=vectors[i:i + batch_size], namespace=namespace)

    def store_resume_data(self, session_id: str, resume_data: Dict[str, Any]):
        vectors = []
        for skill in resume_data.get("skills", []):
            vector = self.embeddings.embed_query(skill)
            vectors.append({
                "id": str(uuid.uuid4()),
                "values": vector,
                "metadata": {"session_id": session_id, "type": "skill", "content": skill},
            })
        if vectors:
            self._upsert_batch("resume", vectors)

    def store_jd_requirements(self, session_id: str, jd_requirements: Dict[str, Any]):
        vectors = []
        for skill in jd_requirements.get("required_skills", []):
            vector = self.embeddings.embed_query(skill)
            vectors.append({
                "id": str(uuid.uuid4()),
                "values": vector,
                "metadata": {
                    "session_id": session_id,
                    "type": "requirement",
                    "content": skill,
                    "priority": "high",
                },
            })
        if vectors:
            self._upsert_batch("jd", vectors)

    def store_qa(self, session_id: str, qa_id: int, question: str, answer: str, score: float):
        context = f"Q: {question}\nA: {answer}"
        vector = self.embeddings.embed_query(context)
        self._upsert_batch("qa", [{
            "id": str(uuid.uuid4()),
            "values": vector,
            "metadata": {
                "session_id": session_id,
                "question": question,
                "answer": answer,
                "score": score,
            },
        }])

    def search_relevant_topics(self, query: str, session_id: str, limit: int = 3) -> List[str]:
        query_vector = self.embeddings.embed_query(query)
        results = self.index.query(
            vector=query_vector,
            top_k=limit,
            namespace="jd",
            filter={"session_id": {"$eq": session_id}},
            include_metadata=True,
        )
        return [m["metadata"]["content"] for m in results["matches"]]

    def multi_search_relevant_topics(
        self,
        queries: List[str],
        session_id: str,
        limit_per_query: int = 5,
        final_limit: int = 3,
    ) -> List[str]:
        """Multi-query retrieval with Reciprocal Rank Fusion (RRF, k=60)."""
        rrf_scores: Dict[str, float] = {}
        topic_content: Dict[str, str] = {}
        K = 60

        for query in queries:
            if not query.strip():
                continue
            try:
                query_vector = self.embeddings.embed_query(query)
                results = self.index.query(
                    vector=query_vector,
                    top_k=limit_per_query,
                    namespace="jd",
                    filter={"session_id": {"$eq": session_id}},
                    include_metadata=True,
                )
                for rank, match in enumerate(results["matches"], start=1):
                    content = match["metadata"].get("content", "")
                    if not content:
                        continue
                    topic_id = content.lower().strip()
                    topic_content[topic_id] = content
                    rrf_scores[topic_id] = rrf_scores.get(topic_id, 0) + (1.0 / (rank + K))
            except Exception as e:
                print(f"Multi-search query failed: {e}")
                continue

        sorted_topics = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return [topic_content[tid] for tid, _ in sorted_topics[:final_limit]]

    def delete_session_data(self, session_id: str):
        for namespace in ["resume", "jd", "qa"]:
            try:
                self.index.delete(
                    filter={"session_id": {"$eq": session_id}},
                    namespace=namespace,
                )
            except Exception as e:
                print(f"[cleanup] Pinecone warning ({namespace}): {e}")
