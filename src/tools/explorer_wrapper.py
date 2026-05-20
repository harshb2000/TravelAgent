from models.knowledge_state import (
    KnowledgeState,
    UserContext,
    DestinationCandidate,
    build_wordset,
)
from specialists.explorer import ExplorerSpecialist, EXPLORER_CACHE_THRESHOLD
from tools.base import BaseTool


class ExplorerWrapperTool(BaseTool):
    name = "explorer"
    description = (
        "Discover destination candidates that match the user's travel intent. "
        "Call this when the answer space is unknown — the right destination is itself the question."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Positive-intent exploration query derived from UserContext. "
                    "Rewrite the user's intent in clean, affirmative terms — include all relevant positive signals "
                    "(activity type, budget tier, geography, travel style) and omit negations entirely. "
                    "Negatives are handled separately via UserContext.blocklist and must not appear in this string. "
                    "Example: user says 'trip in SEA, not too heavy on nightlife, more nature focused' → "
                    "pass 'nature focused trip in South East Asia'."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of new candidates to return (default 5).",
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        specialist: ExplorerSpecialist,
        knowledge: KnowledgeState,
        user_context: UserContext,
    ):
        self._specialist = specialist
        self._knowledge = knowledge
        self._user_context = user_context

    def execute(self, **kwargs) -> dict:
        query: str = kwargs.get("query", "")
        max_results: int = int(kwargs.get("max_results", 5))

        uc = self._user_context
        ks = self._knowledge

        # Stage 1: drop any cached candidate that should be excluded based on
        # the user's blocklist (name/country hard match, or tag majority rule).
        eligible_cached = [c for c in ks.candidates if not c.should_exclude(uc.blocklist)]

        # Stage 2: of the eligible cached candidates, keep only those whose content
        # is sufficiently relevant to the current query (Jaccard on positive wordsets).
        # Recency is intentionally not considered here — an older but relevant candidate
        # is still valid cache data. Recency only affects presentation order in to_prompt_context.
        query_wordset = build_wordset(query, uc.blocklist)
        scored_cached: list[tuple[float, DestinationCandidate]] = []
        for c in eligible_cached:
            combined = c.wordset | query_wordset
            if combined:
                score = len(c.wordset & query_wordset) / len(combined)
                if score >= EXPLORER_CACHE_THRESHOLD:
                    scored_cached.append((score, c))

        # Sort by relevance score so slicing always returns the best matches first
        scored_cached.sort(key=lambda x: -x[0])
        relevant_cached = [c for _, c in scored_cached]
        n_relevant_cached = len(relevant_cached)

        try:
            if n_relevant_cached >= max_results:
                # Full cache hit — the cached candidates already cover this query
                summary = self._template_summary(relevant_cached[:max_results], cached=n_relevant_cached, new=0)
                return {"status": "ok", "summary": summary, "from_cache": True, "cached": True}

            # Partial or full miss — call the specialist for the remaining slots.
            # Embed negative constraints explicitly so the LLM respects them even if
            # the positive-intent query doesn't surface them.
            constrained_query = query
            if uc.blocklist:
                exclusions = " ".join(f"not {t}" for t in sorted(uc.blocklist))
                constrained_query = f"{query} (exclude: {exclusions})"

            new_candidates = self._specialist.run(
                query=constrained_query,
                max_results=max_results - n_relevant_cached,
                existing_candidates=relevant_cached if relevant_cached else None,
            )

            ks.add_candidates(new_candidates)

            all_results = relevant_cached + new_candidates
            summary = self._template_summary(all_results, cached=n_relevant_cached, new=len(new_candidates))
            return {"status": "ok", "summary": summary}

        except Exception as e:
            return {"status": "error", "summary": f"ExplorerSpecialist failed: {e}"}

    @staticmethod
    def _template_summary(
        candidates: list[DestinationCandidate], cached: int, new: int
    ) -> str:
        total = len(candidates)
        if cached and new:
            header = f"Found {total} candidates [{cached} from cache, {new} new]:"
        elif cached:
            header = f"Found {total} candidates [from cache]:"
        else:
            header = f"Found {total} candidates:"

        lines = [header]
        for c in candidates:
            tags = ", ".join(c.vibe_tags) if c.vibe_tags else "—"
            lines.append(f"  {c.name} ({c.country}) — {tags} [{c.source_url}]")
        return "\n".join(lines)
