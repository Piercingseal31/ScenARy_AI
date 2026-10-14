import string
import os
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from ollama import chat
import firebase_admin
from firebase_admin import credentials, firestore

# 1. Initialize Firebase (This stays at the top)
cred = credentials.Certificate("serviceAccountKey.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# 2. Paste the dynamic loader function right here!
def load_landmarks_from_firebase():
    print("Fetching marker data and linked content from Firebase...")
    markers_ref = db.collection("markers")
    docs = markers_ref.stream()
    
    landmarks_data = {}
    for doc in docs:
        data = doc.to_dict()
        landmark_id = doc.id
        
        name = data.get("landmarkName") or data.get("institutionName") or data.get("name", "Unknown Landmark")
        location = data.get("location", "Cebu City, Philippines")
        content_ids = data.get("contentIds", [])
        
        rich_description = data.get("description", "")
        fun_facts = []
        quizzes = []
        
        for cid in content_ids:
            content_doc = db.collection("content").document(cid).get()
            if content_doc.exists:
                c_data = content_doc.to_dict()
                c_type = c_data.get("type", "")
                c_payload = c_data.get("data", {})
                
                if c_type == "Information":
                    desc = c_payload.get("description", "")
                    if desc and desc not in rich_description:
                        rich_description += "\n" + desc
                elif c_type == "Fun Fact":
                    fact = c_payload.get("fact", "")
                    if fact:
                        fun_facts.append(fact)
                elif c_type == "Quiz":
                    qs = c_payload.get("quizzes", [])
                    quizzes.extend(qs)

        # Auto-generate dynamic keywords from your actual Firebase text
        text_corpus = (rich_description + " " + " ".join(fun_facts)).lower()
        stop_words = {"the", "and", "a", "to", "of", "in", "is", "it", "with", "as", "at", "by", "an", "on"}
        extracted_words = [
            w.strip("?!.,:;()\"'") 
            for w in text_corpus.split() 
            if len(w) > 3 and w not in stop_words
        ]
        dynamic_keywords = list(set(extracted_words))[:30]

        landmarks_data[landmark_id] = {
            "name": name,
            "location": location,
            "description": rich_description,
            "fun_facts": fun_facts,
            "quizzes": quizzes,
            "keywords": dynamic_keywords
        }
        print(f" -> Loaded '{name}' with {len(fun_facts)} fun facts and {len(quizzes)} quiz items.")
        
    return landmarks_data

# 3. Call the function to load everything into memory when the script starts
LANDMARKS = load_landmarks_from_firebase()

# ========================================
# 2. HELPER FUNCTIONS & SCRAPER
# ========================================

BLOCKED_DOMAINS = [
    "facebook.com", "instagram.com", "twitter.com", "x.com", 
    "tiktok.com", "youtube.com", "reddit.com", "pinterest.com", 
    "linkedin.com", "wikiwand.com"
]

SYNONYM_MAP = {
    "wife": ["spouse", "married", "marry", "marriage", "consort", "bride"],
    "husband": ["spouse", "married", "marry", "marriage", "consort"],
    "parents": ["father", "mother", "born", "son of", "daughter of", "family", "parentage"],
    "father": ["parent", "born", "son of"],
    "mother": ["parent", "born", "son of"],
    "founded": ["built", "established", "constructed", "foundation", "created", "erected"]
}

def is_question_in_scope(question, conversation_history, selected_landmark):
    landmark_name = selected_landmark['name'].lower()
    q_lower = question.lower()
    q_words = [w.strip("?!.,:;\"'") for w in q_lower.split()]

    # 1. DIRECT MATCH SHORTCUT (Landmark name)
    if landmark_name in q_lower:
        print(f"  [SCOPE CHECK] Allowed: True (Matched landmark name)")
        return True

    # 2. DYNAMIC FIREBASE KEYWORD MATCH 
    landmark_keywords = [kw.lower() for kw in selected_landmark.get("keywords", [])]
    if any(kw in q_lower for kw in landmark_keywords if len(kw) > 3):
        print(f"  [SCOPE CHECK] Allowed: True (Matched Firebase database keyword)")
        return True

    # 3. UNIVERSAL GRAMMAR PRONOUNS ONLY (Language scaffolding, no domain facts)
    follow_up_triggers = [
        "it", "there", "they", "its", "their", "this", "here", 
        "who", "he", "she", "him", "his", "her", "them"
    ]
    if any(trigger in q_words for trigger in follow_up_triggers):
        print(f"  [SCOPE CHECK] Allowed: True (Detected universal pronoun/reference word)")
        return True

    # 4. DYNAMIC QWEN INTELLIGENCE (Context fallback)
    history_context = ""
    if conversation_history:
        last_turn = conversation_history[-1]
        history_context = f"Previous Q: {last_turn['question']}\nPrevious A: {last_turn['answer']}\n"

    landmark_summary = selected_landmark.get("description", "")[:400]

    prompt = f"""Target Landmark: "{selected_landmark['name']}"
Firebase Database Summary: {landmark_summary}
{history_context}Current Question: "{question}"
Is this question asking about {selected_landmark['name']} or the historical figures/events mentioned in its database summary? Answer only YES or NO."""

    try:
        response = chat(
            model="qwen2.5:1.5b",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0, "num_ctx": 512}
        )
        content = response["message"]["content"].strip().upper()
        if "</think>" in content:
            content = content.split("</think>")[-1].strip().upper()
    
        decision = "YES" in content
        print(f"  [SCOPE CHECK] Allowed: {decision} (Model output: {content})")
        return decision
    except Exception as e:
        print(f"  [SCOPE CHECK ERROR]: {e}")
        return False

def fetch_page(url):
    if any(domain in url.lower() for domain in BLOCKED_DOMAINS):
        print(f"Skipping social media link: {url}")
        return []

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        response = requests.get(url, timeout=5, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        paragraphs = []
        for paragraph in soup.find_all("p"):
            text = paragraph.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)

        return paragraphs[:50]
    except Exception:
        return []

def get_relevant_paragraphs(paragraphs, question, landmark_context, conversation_context):
    raw_question_words = [
        w.lower().strip("?!.,:;\"'") 
        for w in question.split() 
        if len(w) > 2 and w.lower() not in ["what", "who", "where", "when", "how", "was", "his", "her", "their", "the"]
    ]
    
    target_keywords = set(raw_question_words)
    for word in raw_question_words:
        if word in SYNONYM_MAP:
            target_keywords.update(SYNONYM_MAP[word])

    scored_paragraphs = []
    for paragraph in paragraphs:
        p_lower = paragraph.lower()
        score = sum(5 for kw in target_keywords if kw in p_lower)
        
        if selected_landmark['name'].lower() in p_lower:
            score += 1

        if score > 0:
            scored_paragraphs.append((score, paragraph))

    scored_paragraphs.sort(key=lambda item: item[0], reverse=True)
    return [paragraph for _, paragraph in scored_paragraphs[:12]]

def generate_search_query(question, conversation_history, selected_landmark):
    # If there's conversation history, resolve pronouns using the local model
    if conversation_history:
        history_text = ""
        for turn in conversation_history[-2:]:
            history_text += f"Q: {turn['question']}\nA: {turn['answer']}\n"

        prompt = f"""Conversation History:
{history_text}

Current Question: "{question}"

Task: Rewrite the Current Question into a standalone search query. Replace any pronouns (he, him, his, it, that) with the exact names or subjects mentioned in the conversation history.
Output ONLY the short search query (3 to 6 words), nothing else."""

        try:
            response = chat(
                model="qwen2.5:1.5b",
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_ctx": 384}
            )
            query = response["message"]["content"].strip()
            if "</think>" in query:
                query = query.split("</think>")[-1].strip()
            
            # Clean up quotes or extra formatting
            query = query.replace('"', '').replace("'", "").strip()
            
            if query and len(query) < 80:
                print(f"  [DYNAMIC QUERY]: '{query}'")
                return query
        except Exception as e:
            print(f"  [QUERY GEN ERROR]: {e}")

    # Fallback for standalone questions
    return f"{selected_landmark['name']} {question}"

# ========================================
# 3. SELECT LANDMARK MENU
# ========================================

print("\nAvailable landmarks:")
landmark_ids = list(LANDMARKS.keys())

for index, landmark_id in enumerate(landmark_ids, start=1):
    landmark = LANDMARKS[landmark_id]
    print(f"{index}. {landmark['name']} ({landmark['location']})")

while True:
    landmark_choice = input("\nSelect a landmark: ")
    try:
        landmark_index = int(landmark_choice) - 1
        if 0 <= landmark_index < len(landmark_ids):
            break
        print("Please select a valid landmark number.")
    except ValueError:
        print("Please enter a number.")

selected_landmark_id = landmark_ids[landmark_index]
selected_landmark = LANDMARKS[selected_landmark_id]

# Format your Firebase fun facts nicely for the AI
fun_facts_text = "\n".join([f"- {fact}" for fact in selected_landmark.get("fun_facts", [])])

landmark_context = f"""
Landmark: {selected_landmark["name"]}
Location: {selected_landmark["location"]}
Description: {selected_landmark["description"]}
Curated Fun Facts from Database:
{fun_facts_text}
"""

instructions = f"""You are ScenARy AI, a historical guide dedicated STRICTLY to {selected_landmark['name']} in {selected_landmark['location']}.

CRITICAL BOUNDARIES & ACCURACY RULES:
1. STRICT FACTUALITY & NO AGE GUESSING:
   - Only state facts, dates, or numbers that appear EXPLICITLY in the retrieved context.
   - Do NOT calculate, estimate, or guess a person's age or birth year if it is not explicitly written in the text.
   - If the retrieved sources do not explicitly state the requested detail, state clearly: "The retrieved historical records do not provide that specific detail."
2. DIRECT ANSWERING:
   - Directly answer the user's specific question using the retrieved context. Do NOT repeat generic introductory sentences or canned summaries if they do not answer the prompt.
3. HISTORICAL ATTRIBUTION:
   - Accurately name the specific groups, nationalities, or leaders explicitly mentioned in the retrieved historical sources.
4. ONLY answer questions directly related to {selected_landmark['name']} ({selected_landmark['location']}) or its historical figures.
5. VENUE ISOLATION:
   - Stay focused strictly on {selected_landmark['name']} in {selected_landmark['location']}.
   - Do NOT confuse {selected_landmark['name']} with other sites built by the same historical figures in different cities.
6. SUBJECT CONSISTENCY & ACCURACY:
   - Stay focused strictly on the primary historical figure being asked about. Do NOT attribute facts belonging to secondary figures to the main subject.
7. REFUSAL POLICY:
   - If the user asks about a DIFFERENT landmark (e.g., Magellan's Cross, Basilica, Eiffel Tower), YOU MUST DECLINE TO ANSWER.
   - Decline statement: "I am currently set up as your guide for {selected_landmark['name']}. I can only answer questions related to this landmark!"
8. FALLBACK POLICY:
   - If retrieved sources do not contain the specific detail requested, state clearly: "The retrieved historical records do not provide that specific detail."
9. Keep answers concise, factual, and direct. Do not invent historical facts.
"""

print(f"\nSelected landmark: {selected_landmark['name']}")

# ========================================
# 4. MAIN CHAT LOOP
# ========================================

conversation_history = []

while True:
    question = input("\nYou: ").strip()

    if question.lower() in ["exit", "quit", "bye"]:
        print("\nSCENARY AI: Goodbye!")
        break

    if not question:
        continue

    in_scope = is_question_in_scope(question, conversation_history, selected_landmark)

    if not in_scope:
        print("\n" + "=" * 50)
        print("SCENARY AI")
        print("=" * 50)
        print(f"I am currently set up as your guide for {selected_landmark['name']}. I can only answer questions related to this landmark!")
        print("=" * 50)
        continue

    conversation_context = ""
    if conversation_history:
        for turn in conversation_history[-3:]:
            conversation_context += f"Previous question: {turn['question']}\nPrevious answer: {turn['answer']}\n"

    search_query = generate_search_query(question, conversation_history, selected_landmark)
    print(f"\nSearching for: \"{search_query}\"...")

    search_results = []
    try:
        with DDGS() as ddgs:
            search_results = list(ddgs.text(f"{search_query} english", region="us-en", max_results=8))

        search_results = [
            r for r in search_results 
            if not any(domain in r.get("href", "").lower() for domain in BLOCKED_DOMAINS)
        ]
    except Exception as e:
        print(f"Search warning: {e}")

    preferred_domains = [
        "nhcp.gov.ph", "gov.ph", ".edu.ph", "museum", "archive.org", "kahibalo.com"
    ]

    results = sorted(
        search_results,
        key=lambda r: any(domain in r.get("href", "").lower() for domain in preferred_domains),
        reverse=True
    )[:2]

    if not results:
        print("\nSCENARY AI: I couldn't find enough information to answer that question.")
        continue

    source_information = ""
    for result in results:
        title = result.get("title", "Untitled")
        url = result.get("href", "")
        snippet = result.get("body", "")

        print(f"Reading: {title}")
        paragraphs = fetch_page(url)

        relevant_paragraphs = get_relevant_paragraphs(
            paragraphs, question, landmark_context, conversation_context
        )

        if relevant_paragraphs:
            relevant_text = "\n".join(relevant_paragraphs) + f"\n\nSEARCH RESULT DESCRIPTION:\n{snippet}\n"
        else:
            relevant_text = snippet

        source_information += f"\nSOURCE: {title}\nURL: {url}\nRELEVANT INFORMATION:\n{relevant_text}\n"

    # === NEW ANTI-HALLUCINATION SAFETY NET ===
    if not source_information.strip() or len(source_information.strip()) < 30:
        print("\n" + "=" * 50)
        print("SCENARY AI")
        print("=" * 50)
        print("The retrieved historical records do not provide that specific detail.")
        print("=" * 50)
        conversation_history.append({
            "question": question,
            "answer": "The retrieved historical records do not provide that specific detail."
        })
        continue
    # =========================================

    if len(source_information) > 12000:
        source_information = source_information[:12000] + "\n[Text truncated due to length]"

    try:
        response = chat(
            model="qwen2.5:1.5b",
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": f"Conversation history:\n{conversation_context}\n\nRetrieved information:\n{source_information}\n\nCurrent question:\n{question}"
                }
            ],
            options={"temperature": 0.1, "num_ctx": 4096}
        )

        answer = response["message"]["content"]
        if "</think>" in answer:
            answer = answer.split("</think>")[-1]
        
        print("\n" + "=" * 50)
        print("SCENARY AI")
        print("=" * 50)
        print(answer.strip())
        print("=" * 50)

        conversation_history.append({
            "question": question,
            "answer": answer.strip()
        })
    except Exception as e:
        print(f"\nError generating response: {e}")