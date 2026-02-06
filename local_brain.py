import json
import os
import random
import logging
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.exceptions import NotFittedError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LocalBrain")

import re
import difflib

class EntityExtractor:
    @staticmethod
    def extract_destination(text):
        # Heuristic: "to [Words]" or "in [Words]"
        # Stop capturing at common prepositions or end of string
        match = re.search(r'\b(to|in|visit|at)\s+([a-zA-Z\s]+?)(?=\s+(?:for|with|on|from|at)|$)', text, re.IGNORECASE)
        if match:
            dest = match.group(2).strip()
            # Clean up if it captured too much or looks wrong?
            # For now, trust the regex boundaries.
            return dest.title() # Convert to Title Case
        
        # Fallback: Check for just a capitalized word if the text is short (like "Goa")
        # But only if it looks like a proper noun (Title Case)
        if len(text.split()) <= 2 and text[0].isupper():
             return text.strip()
             
        return None

    @staticmethod
    def extract_duration(text):
        # "for X days", "X weeks", "weekend", "fortnight"
        match = re.search(r'(?:for\s+)?(\d+\s+(?:day|week|month)s?|weekend|fortnight)', text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
    
    @staticmethod
    def extract_budget(text):
        # Heuristic: $X, X dollars, X rs
        match = re.search(r'([$₹€£]\s*\d+(?:,\d+)?|\d+(?:,\d+)?\s*(?:dollars|rupees|usd|inr))', text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

class LocalBrain:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        self.training_file = os.path.join(data_dir, "training_data.json")
        self.kb_file = os.path.join(data_dir, "knowledge_base.json")
        self.model_file = os.path.join(data_dir, "brain_model.pkl")
        
        self.model = None
        self.intents = {}
        self.knowledge_base = {}
        # Context: {user_id: {"last_intent": str, "state": str, "slots": {}, "history": []}}
        self.context = {} 

        self.load_knowledge_base()
        self.train_model()


    def load_knowledge_base(self):
        try:
            if os.path.exists(self.kb_file):
                with open(self.kb_file, 'r') as f:
                    self.knowledge_base = json.load(f)
                logger.info("Knowledge Base loaded.")
            else:
                logger.warning("Knowledge Base file not found.")
        except Exception as e:
            logger.error(f"Error loading Knowledge Base: {e}")

    def train_model(self):
        """
        Trains a TF-IDF + Logistic Regression model on the training data.
        """
        try:
            if not os.path.exists(self.training_file):
                logger.error("Training data file not found.")
                return

            with open(self.training_file, 'r') as f:
                data = json.load(f)

            patterns = []
            labels = []
            self.intents = {}

            for intent in data["intents"]:
                tag = intent["tag"]
                self.intents[tag] = intent
                for pattern in intent["patterns"]:
                    patterns.append(pattern)
                    labels.append(tag)

            # Create pipeline
            # Using (1,1) unigrams because data is small, avoiding sparsity of bigrams
            self.model = make_pipeline(
                TfidfVectorizer(ngram_range=(1, 1), stop_words='english'),
                LogisticRegression(random_state=42, max_iter=1000, C=10.0) # Higher C for less regularization on small data
            )

            # Train
            self.model.fit(patterns, labels)
            logger.info(f"Model trained on {len(patterns)} examples across {len(self.intents)} intents.")

            # Save model (optional, for persistence across restarts without retraining)
            # with open(self.model_file, 'wb') as f:
            #     pickle.dump(self.model, f)

        except Exception as e:
            logger.error(f"Error training model: {e}")

    def predict_intent(self, text):
        """
        Returns (intent, confidence_score)
        """
        if not self.model:
            return None, 0.0

        try:
            # Get probabilities
            probs = self.model.predict_proba([text])[0]
            max_prob = max(probs)
            pred_idx = probs.argmax()
            intent = self.model.classes_[pred_idx]
            
            return intent, max_prob
        except NotFittedError:
            logger.error("Model not fitted.")
            return None, 0.0
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return None, 0.0

    def update_context(self, user_id, intent, text, role="user"):
        if user_id not in self.context:
            self.context[user_id] = {
                "last_intent": None, 
                "state": "IDLE", 
                "slots": {}, 
                "history": []
            }
        
        # Only update intent if confidence was high enough (passed to this method) and it's a user
        if role == "user" and intent:
            self.context[user_id]["last_intent"] = intent
            
        self.context[user_id]["history"].append({"role": role, "text": text, "intent": intent})
        # Keep last 10 interactions for broader context
        if len(self.context[user_id]["history"]) > 10:
            self.context[user_id]["history"].pop(0)

    def handle_dialogue(self, user_id, intent, text):
        """
        Manages state transitions and slot filling.
        Returns:
            - str: A text response if the dialogue continues.
            - dict: An action object if a task is complete (e.g., {"text": "...", "action": "create_trip", "params": {...}})
            - None: If no dialogue state is active/relevant.
        """
        ctx = self.context[user_id]
        state = ctx["state"]
        slots = ctx["slots"]
        
        # Extract entities regardless of state (opportunistic filling)
        dest = EntityExtractor.extract_destination(text)
        if dest: slots["destination"] = dest
        
        dur = EntityExtractor.extract_duration(text)
        if dur: slots["duration"] = dur
        
        bg = EntityExtractor.extract_budget(text)
        if bg: slots["budget"] = bg

        # 1. Plan Trip Flow
        if intent == "plan_trip" or state == "PLANNING":
            # Check for intent switch (if user asks about something else while planning)
            # Only switch if confidence is high (> 0.6) to avoid false positives on short answers
            _, confidence = self.predict_intent(text)
            
            # Special case: If user explicitly says "plan a trip" again, RESTART the flow
            if intent == "plan_trip" and confidence > 0.8:
                 ctx["state"] = "PLANNING"
                 ctx["slots"] = {} # RESET SLOTS
                 slots = ctx["slots"] # Update local reference to the new dictionary
                 
                 # Re-extract from current text in case they said "Plan a trip to Paris" (restart with new dest)
                 dest = EntityExtractor.extract_destination(text)
                 if dest: slots["destination"] = dest
                 dur = EntityExtractor.extract_duration(text)
                 if dur: slots["duration"] = dur
                 bg = EntityExtractor.extract_budget(text)
                 if bg: slots["budget"] = bg
            
            elif state == "PLANNING" and intent != "plan_trip" and confidence > 0.6:
                known_intents = ["packing_help", "budget_help", "weather_check", "food_suggestion", "bot_identity"]
                if intent in known_intents:
                    ctx["state"] = "IDLE"
                    return None # Allow main logic to handle the new intent

            ctx["state"] = "PLANNING"
            
            if not slots.get("destination"):
                if intent == "plan_trip": # Only prompt if we just started or are strictly in flow
                     return "Where are you planning to go?"
                
                # Contextual Fallback: If we are here, we ASKED for a destination.
                if not dest and len(text.split()) <= 4:
                     dest = text.strip().title()
                     slots["destination"] = dest

                if dest: # We just found the destination
                     return f"Great! A trip to **{dest}**. How long are you planning to stay?"
                else:
                     return "I didn't quite catch the destination. Where are you planning to go? (e.g., 'To Paris')"
            elif not slots.get("duration"):
                # If we just got the duration
                if dur:
                    # COMPLETE!
                    response_text = f"I've noted that down: A {dur} trip to **{slots['destination']}**."
                    if slots.get("budget"):
                        response_text += f" with a budget of {slots['budget']}."
                    
                    response_text += "\n\n🚀 **Autonomous Action:** I have enough info to create this trip."
                    
                    action_payload = {
                        "text": response_text,
                        "action": "create_trip",
                        "params": {
                            "trip_name": slots["destination"],
                            "duration": slots["duration"]
                        }
                    }
                    
                    ctx["state"] = "IDLE"
                    ctx["slots"] = {}
                    return action_payload
                else:
                    return f"Great! A trip to **{slots['destination']}**. How long are you planning to stay?"
            else:
                # Should be done (Fallthrough if we somehow have both slots but came here)
                response_text = f"I've noted that down: A {slots['duration']} trip to **{slots['destination']}**."
                if slots.get("budget"):
                    response_text += f" with a budget of {slots['budget']}."
                
                action_payload = {
                    "text": response_text,
                    "action": "create_trip",
                    "params": {
                        "trip_name": slots["destination"],
                        "duration": slots["duration"]
                    }
                }
                ctx["state"] = "IDLE" # Reset
                ctx["slots"] = {} # Clear slots after completion
                return action_payload
                
        return None

    def generate_response(self, user_id, text):
        """
        Main entry point for getting a response.
        """
        intent, confidence = self.predict_intent(text)
        logger.info(f"Query: '{text}' | Intent: {intent} | Conf: {confidence:.2f}")

        # Initialize context if needed
        if user_id not in self.context:
            self.update_context(user_id, None, text, role="user")

        # 1. Update User Context
        self.update_context(user_id, intent, text, role="user")
        
        response = None

        # 2. Check for Dialogue/State-based response first
        dialogue_response = self.handle_dialogue(user_id, intent, text)
        if dialogue_response:
            response = dialogue_response

        # 3. Fallback to ML/Rule-based if no dialogue response
        if not response:
            # Threshold for ML confidence
            if confidence < 0.25:
                response = None # Fallback to other systems (search/heuristics)
            else:
                # Rule-based overrides based on context or keywords
                text_lower = text.lower()
                if "tip" in text_lower or "hack" in text_lower:
                     tips = self.knowledge_base.get("travel_hacks", [])
                     if tips:
                         response = f"💡 **Travel Hack:** {random.choice(tips)}"

                elif intent in self.intents:
                    responses = self.intents[intent]["responses"]
                    base_response = random.choice(responses)
                    response = base_response
                    
                    # --- Context-Aware Enhancements ---
                    slots = self.context[user_id].get("slots", {})
                    dest = slots.get("destination")

                    if intent == "weather_check" and dest:
                         response = f"I can't check real-time weather yet, but for **{dest}**, you should definitely pack layers! 🌤️"
                    
                    elif intent == "budget_help" and dest:
                         response = f"Planning a budget for **{dest}**? Smart move! " + base_response

                    # Dynamic injections based on Knowledge Base
                    if intent == "packing_help":
                        # Check for specific types in query
                        found_type = None
                        available_types = list(self.knowledge_base.get("packing_suggestions", {}).keys())
                        
                        # 1. Exact match
                        for type_key in available_types:
                            if type_key in text_lower:
                                found_type = type_key
                                break
                        
                        # 2. Fuzzy match if no exact match
                        if not found_type:
                            words = text_lower.split()
                            for word in words:
                                matches = difflib.get_close_matches(word, available_types, n=1, cutoff=0.7)
                                if matches:
                                    found_type = matches[0]
                                    break
                        
                        if found_type:
                            items = ", ".join(self.knowledge_base["packing_suggestions"][found_type][:5])
                            response += f"\n\n🎒 **{found_type.capitalize()} Essentials:** {items}, etc."
                        elif dest: # Context fallback
                             response += f"\nFor **{dest}**, don't forget your travel documents!"

        # 4. Update Bot Context and Return
        if response:
             self.update_context(user_id, None, response, role="bot")
             
        return response

if __name__ == "__main__":
    # Test run
    brain = LocalBrain()
    
    # Test 1: Simple Q&A
    print("\n--- Test 1: Simple Q&A ---")
    print(brain.generate_response("user1", "Hi there"))
    
    # Test 2: Multi-turn Planning
    print("\n--- Test 2: Planning Flow ---")
    print(brain.generate_response("user2", "I want to plan a trip"))
    print(brain.generate_response("user2", "to Goa"))
    print(brain.generate_response("user2", "for 5 days"))
    
    # Test 3: Interruption
    print("\n--- Test 3: Interruption ---")
    print(brain.generate_response("user3", "Plan a trip to Paris"))
    print(brain.generate_response("user3", "Actually what is the weather like?")) # Should switch
    
    # Test 5: Contextual Queries
    print("\n--- Test 5: Contextual Queries ---")
    print(brain.generate_response("user5", "Plan a trip to London"))
    print(brain.generate_response("user5", "What is the weather like?")) # Should mention London
    
    print("\n--- Test 6: Contextual Packing ---")
    print(brain.generate_response("user6", "Plan a trip to Hawaii"))
    print(brain.generate_response("user6", "What should I pack?")) # Should mention Hawaii context
