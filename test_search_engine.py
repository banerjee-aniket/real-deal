import unittest
from unittest.mock import MagicMock, patch
from search_engine import SearchEngine

class TestSearchEngine(unittest.TestCase):
    def setUp(self):
        self.engine = SearchEngine()

    def test_validate_query_valid(self):
        valid, msg = self.engine.validate_query("hotels in Paris")
        self.assertTrue(valid)
        self.assertEqual(msg, "")

    def test_validate_query_empty(self):
        valid, msg = self.engine.validate_query("")
        self.assertFalse(valid)
        self.assertEqual(msg, "Query cannot be empty.")

    def test_validate_query_too_short(self):
        valid, msg = self.engine.validate_query("hi")
        self.assertFalse(valid)
        self.assertEqual(msg, "Query is too short (min 3 chars).")

    def test_calculate_relevance_score(self):
        query = "best pizza"
        
        # High relevance: contains both "best" and "pizza" in title
        res1 = {'title': "Best Pizza in Town", 'body': "We serve pizza."}
        score1 = self.engine.calculate_relevance_score(query, res1)
        # best(3) + pizza(3) + pizza_body(1) = 7
        self.assertEqual(score1, 7)

        # Low relevance: only body match
        res2 = {'title': "Food Blog", 'body': "I ate some pizza."}
        score2 = self.engine.calculate_relevance_score(query, res2)
        # pizza_body(1) = 1
        self.assertEqual(score2, 1)

    @patch('search_engine.DDGS')
    def test_search_returns_sorted_results(self, mock_ddgs_cls):
        # Mock the DDGS context manager and text method
        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value.__enter__.return_value = mock_ddgs_instance
        
        # Mock results (unordered)
        mock_results = [
            {'title': "Irrelevant Result", 'body': "Something else", 'href': "http://a.com"},
            {'title': "Best Hotels in Goa", 'body': "Top rated hotels", 'href': "http://b.com"}, # Relevant
            {'title': "Goa Weather", 'body': "It is hot", 'href': "http://c.com"} # Semi-relevant
        ]
        
        # ddgs.text returns an iterator/generator
        mock_ddgs_instance.text.return_value = iter(mock_results)

        query = "hotels in Goa"
        results = self.engine.search(query)

        # Check if results are sorted by score
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]['title'], "Best Hotels in Goa") # Should be first
        
        # Check filtering (irrelevant result should be filtered out or lower)
        # Irrelevant result score: 0 (neither 'hotels' nor 'goa' in title/body)
        # Threshold is 2. So it should be removed.
        titles = [r['title'] for r in results]
        self.assertNotIn("Irrelevant Result", titles)

if __name__ == '__main__':
    unittest.main()
