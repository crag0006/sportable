"""Retrieval over program descriptions (contract v0.3 section 8.7): the acceptance rule.

The repository ranks (cosine plus BM25, fused); this module decides what the
model is allowed to read. A dense-only candidate must clear the floor; a BM25
hit below it is kept when its score is a large enough share of the query's
maximum attainable score. Both floors are configuration, per embedding model.
"""

from dataclasses import dataclass

from app.core.config import AssistantConfig
from app.gateways.protocols import EmbeddingModel
from app.repositories.protocols import ChunkRepository, ChunkRow


@dataclass(frozen=True)
class Passage:
    """A passage the model may read, with what the trace shows the user."""

    program_id: str
    title: str | None
    text: str
    source_id: str
    publisher_page: str | None
    similarity: float
    lexical_hit: bool

    @property
    def href(self) -> str:
        """The event page of the program the passage belongs to."""
        return f"/events/{self.program_id}"


def keep(similarity: float, lexical: bool, ratio: float, cfg: AssistantConfig) -> bool:
    """The acceptance rule.

    Measured on 10 Oct 2026 over 18 questions: relevant BM25 ratios ran 0.45 to
    0.63 and off-topic ones 0.10 to 0.29, so the floor sits between them.
    """
    if similarity >= cfg.relevance_floor:
        return True
    if not lexical:
        return False
    if ratio >= cfg.bm25_ratio_floor:
        return True
    return ratio >= cfg.bm25_ratio_soft and similarity >= cfg.relevance_floor - cfg.lexical_margin


@dataclass(frozen=True)
class Retrieval:
    """Question in, accepted passages out."""

    chunks: ChunkRepository
    embeddings: EmbeddingModel
    model_id: str
    config: AssistantConfig

    def search(self, question: str) -> list[Passage]:
        """Embed once, rank in the database, apply the rule, cap at ``retrieval_top_k``."""
        vector = self.embeddings.embed(question)
        rows = self.chunks.search(vector, question, self.model_id, self.config.retrieval_top_k * 3)
        ratios = getattr(self.chunks, "last_ratios", {})
        kept: list[ChunkRow] = [
            r
            for r in rows
            if keep(
                r.similarity,
                r.lexical_hit,
                ratios.get((r.program_id, r.chunk_index), 0.0),
                self.config,
            )
        ][: self.config.retrieval_top_k]
        titles = self.chunks.titles(sorted({r.program_id for r in kept}))
        return [
            Passage(
                program_id=r.program_id,
                title=titles.get(r.program_id, (None, None))[0],
                text=r.text,
                source_id=r.source_id,
                publisher_page=titles.get(r.program_id, (None, None))[1],
                similarity=round(r.similarity, 3),
                lexical_hit=r.lexical_hit,
            )
            for r in kept
        ]
