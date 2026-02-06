import unittest
import time
from local_brain import LocalBrain

class TestLocalBrain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("Initializing Brain for Tests...")
        cls.brain = LocalBrain()

    def test_intent_classification(self):
        # Test basic intents
        queries = {
            "hello bot": "greeting",
            "plan a trip for me": "plan_trip",
            "packing list for beach": "packing_help",
            "budget tracking": "budget_help"
        }
        
        for query, expected_intent in queries.items():
            intent, conf = self.brain.predict_intent(query)
            print(f"DEBUG: '{query}' -> {intent} ({conf:.2f})")
            self.assertEqual(intent, expected_intent, f"Failed for '{query}'")
            self.assertGreater(conf, 0.25, f"Low confidence for '{query}'")

    def test_response_generation(self):
        resp = self.brain.generate_response("user1", "what should I pack for the beach?")
        self.assertIsNotNone(resp)
        self.assertIn("Beach Essentials", resp)

    def test_context_management(self):
        user_id = "test_user_ctx"
        self.brain.generate_response(user_id, "hello")
        
        ctx = self.brain.context.get(user_id)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["last_intent"], "greeting")
        self.assertEqual(len(ctx["history"]), 1)

    def test_performance_benchmark(self):
        # Requirement: Response time < 500ms
        start_time = time.time()
        for _ in range(100):
            self.brain.generate_response("bench_user", "plan a trip")
        end_time = time.time()
        
        avg_time = (end_time - start_time) / 100
        print(f"\nAverage Inference Time: {avg_time*1000:.2f}ms")
        self.assertLess(avg_time, 0.5, "Inference too slow!")

if __name__ == '__main__':
    unittest.main()
