import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from ollama import chat


# ========================================
# FORT SAN PEDRO SEARCH SCOPE
# ========================================

# This provides the search engine with the
# historical and geographical context of
# the AI's subject.
fort_san_pedro_context = """
Fort San Pedro
Cebu City, Philippines
historical landmark
Spanish colonial fortification
history, construction, architecture, cannons, artillery,
historical events, and cultural significance
"""


# ========================================
# QWEN AI INSTRUCTIONS
# ========================================

# These instructions control how Qwen
# responds to the user's questions.
instructions = """
You are the ScenARy AI assistant.

You answer questions specifically about Fort San Pedro
in Cebu City, Philippines.

Use the retrieved webpage information to answer the user's question.

Rules:
- Answer directly and concisely.
- Use the retrieved information as your primary source.
- Do not invent historical facts.
- If the sources do not provide the answer, say that the information
  was not found.
- If the sources contain conflicting information, mention the conflict.
- Use simple, easy-to-understand language.
- Do not explain your reasoning process.
"""


# ========================================
# GET USER QUESTION
# ========================================

question = input("You: ")


# ========================================
# WEB SEARCH
# ========================================

# Combine the Fort San Pedro context
# with the user's question.
search_query = f"""
{fort_san_pedro_context}
{question}
"""

print("\nSearching...")


# Search for up to five results.
search_results = DDGS().text(
    search_query,
    max_results=5
)


# ========================================
# FILTER SEARCH RESULTS
# ========================================

# Wikipedia is removed because the current
# ScenARy AI prototype should not use it
# as a source.
results = []

for result in search_results:

    url = result["href"].lower()

    if "wikipedia.org" in url:
        continue

    results.append(result)

    # Only use two sources to reduce the
    # amount of information being processed.
    if len(results) == 2:
        break


# ========================================
# FETCH WEBPAGE CONTENT
# ========================================

def fetch_page(url):

    try:

        response = requests.get(
            url,
            timeout=2,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        # Convert the webpage into a
        # searchable HTML structure.
        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # Remove webpage elements that are
        # unlikely to contain useful article text.
        for tag in soup([
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside"
        ]):

            tag.decompose()

        paragraphs = []

        # Extract text from paragraph elements.
        for paragraph in soup.find_all("p"):

            text = paragraph.get_text(
                " ",
                strip=True
            )

            if text:
                paragraphs.append(text)

        # Limit the amount of webpage content
        # processed by the AI.
        return paragraphs[:30]

    except Exception:

        # If a webpage cannot be accessed,
        # return an empty list instead of
        # stopping the entire program.
        return []


# ========================================
# FIND RELEVANT PARAGRAPHS
# ========================================

def get_relevant_paragraphs(
    paragraphs,
    question
):

    # Break the user's question into words
    # that can be compared with webpage text.
    question_words = set(
        question.lower()
        .replace("?", "")
        .replace(",", "")
        .replace(".", "")
        .split()
    )

    relevant = []

    for paragraph in paragraphs:

        paragraph_lower = paragraph.lower()

        score = 0

        # Give points to paragraphs that
        # contain words from the question.
        for word in question_words:

            if len(word) > 3 and word in paragraph_lower:

                score += 2

        if score > 0:

            relevant.append(
                (score, paragraph)
            )

    # Put the most relevant paragraphs first.
    relevant.sort(
        key=lambda item: item[0],
        reverse=True
    )

    # Keep only the four most relevant paragraphs.
    return [
        paragraph
        for score, paragraph in relevant[:4]
    ]


# ========================================
# BUILD SOURCE INFORMATION
# ========================================

source_information = ""


for result in results:

    title = result["title"]
    url = result["href"]
    snippet = result["body"]

    print(f"Reading: {title}")

    # Download and extract the webpage.
    paragraphs = fetch_page(url)

    # Find paragraphs related to the question.
    relevant_paragraphs = get_relevant_paragraphs(
        paragraphs,
        question
    )

    # Use relevant webpage text when available.
    if relevant_paragraphs:

        relevant_text = "\n".join(
            relevant_paragraphs
        )

    # If the webpage cannot be read or
    # contains no matching paragraphs,
    # use the search engine's description.
    else:

        relevant_text = snippet

    source_information += f"""

SOURCE:
{title}

URL:
{url}

RELEVANT INFORMATION:
{relevant_text}

"""


# ========================================
# ASK QWEN
# ========================================

print("\nGenerating answer...")


response = chat(
    model="qwen3:4b",

    messages=[
        {
            "role": "system",
            "content": instructions
        },
        {
            "role": "user",
            "content": f"""
Retrieved information:

{source_information}

Question:
{question}
"""
        }
    ],

    # Disable Qwen's thinking mode where supported.
    think=False,

    options={
        "temperature": 0.3,
        "num_ctx": 2048
    }
)


# ========================================
# CLEAN QWEN RESPONSE
# ========================================

answer = response["message"]["content"]


# Qwen may still include its thinking
# before the final answer. Remove it.
if "</think>" in answer:

    answer = answer.split(
        "</think>"
    )[-1]


# ========================================
# DISPLAY FINAL ANSWER
# ========================================

print("\n" + "=" * 50)
print("SCENARY AI")
print("=" * 50)

print(answer.strip())

print("=" * 50)