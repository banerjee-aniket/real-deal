import logging
from ddgs import DDGS
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SearchEngine:
    def __init__(self):
        self.max_results = 5
        self.min_score_threshold = 2  # Minimum score to be considered "relevant"

    def validate_query(self, query):
        """
        Validates the search query.
        Returns (bool, str): (is_valid, error_message)
        """
        if not query or not isinstance(query, str):
            return False, "Query cannot be empty."
        
        cleaned = query.strip()
        if len(cleaned) < 3:
            return False, "Query is too short (min 3 chars)."
            
        # Basic injection check (not strictly necessary for DDG but good practice)
        if len(cleaned) > 200:
             return False, "Query is too long."
             
        return True, ""

    def calculate_relevance_score(self, query, result):
        """
        Calculates a relevance score for a search result based on the query.
        """
        score = 0
        query_terms = set(re.findall(r'\w+', query.lower()))
        
        # Remove stop words (basic list)
        stop_words = {'the', 'is', 'at', 'which', 'on', 'in', 'a', 'an', 'and', 'or', 'to', 'for', 'of', 'with'}
        query_terms = query_terms - stop_words
        
        if not query_terms:
            return 1 # Fallback if only stop words

        title = result.get('title', '').lower()
        body = result.get('body', '').lower()
        
        for term in query_terms:
            # Title matches are weighted higher
            if term in title:
                score += 3
            # Body matches
            if term in body:
                score += 1
                
        return score

    def search(self, query, context="travel"):
        """
        Performs a web search, scores results, and returns the top relevant ones.
        """
        is_valid, error = self.validate_query(query)
        if not is_valid:
            logger.warning(f"Invalid query: {query} - {error}")
            return []

        # Enhance query with context if it's too generic
        # (Simple heuristic: if no travel words, add context)
        # For now, we trust the user's query but we could append " travel"
        
        try:
            raw_results = []
            with DDGS() as ddgs:
                # Fetch more results than needed to allow for filtering
                # DDGS text search
                ddgs_gen = ddgs.text(query, max_results=10)
                raw_results = list(ddgs_gen)
                
            scored_results = []
            for res in raw_results:
                score = self.calculate_relevance_score(query, res)
                if score >= self.min_score_threshold:
                    res['score'] = score
                    scored_results.append(res)
            
            # Sort by score descending
            scored_results.sort(key=lambda x: x['score'], reverse=True)
            
            return scored_results[:self.max_results]
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

if __name__ == "__main__":
    # Quick manual test
    engine = SearchEngine()
    q = "best time to visit Goa"
    print(f"Searching for: {q}")
    results = engine.search(q)
    for r in results:
        print(f"[{r['score']}] {r['title']}")
