import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from ollama import chat

conversation_history = []

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

search_context = """
Fort San Pedro Cebu Philippines
historical fort
cannons artillery
"""

# ========================================
# QWEN AI INSTRUCTIONS
# ========================================

# These instructions control how Qwen
# responds to the user's questions.
instructions = """
You are the ScenARy AI assistant.

You answer questions about Fort San Pedro in Cebu City,
Philippines, and related historical people, events, and topics
when the user's question requires additional context.

Use the retrieved webpage information as the basis for your answer.

Rules:

- Answer directly and concisely.
- Do not invent historical facts.
- Treat retrieved information as source-based information,
  not as unquestionable truth.
- Base your answer only on the retrieved information and
  conversation context.
- Do not add facts that were not found in the retrieved sources.

SOURCE CONFIDENCE:

- Historical biographical information, including spouses, parents,
  children, family relationships, and places of birth, may be
  answered when supported by the retrieved sources.
- Do not refuse a historical question simply because it concerns
  a person's private or family life.
- If the search fails or no useful source information is retrieved,
  do not infer or invent an answer.
- Never interpret missing information as evidence that something
  did not exist or did not happen.
- For example, if the sources do not mention cannons, do not say
  that the fort had no cannons.
- Instead, state that the retrieved sources did not provide enough
  information to answer the question.
- If multiple retrieved sources support the same information,
  you may say:
  "The sources I found indicate..."
  or
  "Based on the available sources..."

- If only one source supports an important fact, make this clear
  by using wording such as:
  "One source states..."
  or
  "According to the article..."

- If the retrieved sources disagree, explain the disagreement
  instead of choosing one answer without explanation.

- If the retrieved sources provide limited information, answer
  using the information that is available and make the limitation
  clear.

- If at least one retrieved source provides an answer, use that
  information and identify it as coming from that source when
  appropriate.

- If multiple sources provide the same answer, you may present
  the information more confidently while still making it clear
  that it is based on the retrieved sources.

- Only say that the information could not be found when the
  retrieved information genuinely does not contain enough
  information to answer the question.

- Never refuse to answer simply because only one source provides
  the information.

- Do not claim that something has been verified unless the
  retrieved sources provide enough evidence to support that claim.

- Do not make every answer sound uncertain. If the retrieved
  sources clearly agree, answer naturally while still making
  it clear that the information comes from the sources.

SOURCE ATTRIBUTION:

- When useful, identify the source that supports the answer.
- You may mention the article title, website, or both.
- Do not list every source unnecessarily.
- Do not invent source names or authors.

HISTORICAL CONTEXT:

- Pay attention to the historical period being discussed.
- Do not assume that information about the current or later
  Fort San Pedro also applies to the earliest wooden fort.
- If a source gives a historical fact but does not clearly
  identify its historical period, do not present that fact
  as applying to a different period.

CONVERSATION:

- Use previous conversation context when answering follow-up
  questions.
- Understand references such as "he", "she", "his", "her",
  "it", and "they" using the conversation history.
- When a follow-up question requires information about a person
  or event related to Fort San Pedro, use the retrieved information
  about that related subject.

STYLE:

- Use simple, natural, easy-to-understand language.
- Keep answers concise.
- Do not repeatedly begin every answer with "According to the sources."
- Vary source-based wording naturally.
- Do not explain your reasoning process.
"""


# ========================================
# GET USER QUESTION
# ========================================

while True:

    question = input("\nYou: ")

    if question.lower() in ["exit", "quit", "bye"]:
        print("\nSCENARY AI: Goodbye!")
        break

    # ========================================
    # WEB SEARCH
    # ========================================

    conversation_context = ""

    if conversation_history:
        last_question = conversation_history[-1]["question"]
        last_answer = conversation_history[-1]["answer"]

        search_context = f"""
        Previous question:
        {last_question}

        Previous answer:
        {last_answer[:500]}
        """

    follow_up_words = [
    "he",
    "she",
    "him",
    "her",
    "his",
    "hers",
    "they",
    "them",
    "their",
    "there",
    "it",
    "that",
    "those",
    "this"
    ]

    relevance_text = f"""
    {conversation_context}
    {question}
    """

    question_words = set(
        relevance_text.lower()
        .replace("?", "")
        .replace(",", "")
        .replace(".", "")
        .replace(":", "")
        .split()
    )

    is_follow_up = any(
        word in question_words
        for word in follow_up_words
    )

    if is_follow_up and conversation_history:

        previous_answer = conversation_history[-1]["answer"]

        # Check whether the previous answer appears to identify
        # a specific person that the follow-up can refer to.
        capitalized_words = []

        for word in previous_answer.split():

            cleaned_word = word.strip(
                ".,!?():;\"'"
            )

            if (
                len(cleaned_word) > 1
                and cleaned_word[0].isupper()
                and not cleaned_word.isupper()
            ):
                capitalized_words.append(
                    cleaned_word
                )

        has_person_context = len(
            capitalized_words
        ) >= 2

        if has_person_context:

            search_query = f"""
            {fort_san_pedro_context}

            {conversation_context}

            Related person:
            {previous_answer}

            Current question:
            {question}

            Search for historical information related
            to the person and the current question.
            """

        else:

            print(
                "\nSCENARY AI: I'm not sure who you are referring to."
            )

            print(
                "Please provide the person's name or more context."
            )

            continue

    else:

        search_query = f"""
        {fort_san_pedro_context}

        Current question:
        {question}

        Search for historical information specifically
        about Fort San Pedro and the subject of the question.
        """

    print("\nSearching...")


    try:

        search_results = DDGS().text(
        search_query,
        max_results=5
         )

    except Exception:

        print("Search failed. Trying the search again...")

        try:

            search_results = DDGS().text(
                search_query,
                max_results=5
            )

        except Exception:

            print("Search could not find any results.")

            search_results = []


    # ========================================
    # FILTER SEARCH RESULTS
    # ========================================

    # Wikipedia is removed because the current
    # ScenARy AI prototype should not use it
    # as a source.
    results = []

    preferred_domains = [
        "nhcp.gov.ph",
        "gov.ph",
        ".edu.ph",
        "museum",
        "archive.org",
        "kahibalo.com"
    ]

    # First, collect non-Wikipedia results.
    for result in search_results:

        url = result["href"].lower()

        if "wikipedia.org" in url:
            continue

        results.append(result)


    # Sort results so preferred sources come first.
    results.sort(
        key=lambda result: any(
            domain in result["href"].lower()
            for domain in preferred_domains
        ),
        reverse=True
    )


    # Only use two sources.
    results = results[:4]

    if not results:
        print(
            "\nSCENARY AI: I couldn't find enough information to answer that question."
        )
        continue

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
        question,
        search_context
    ):

        # Combine the current question with
        # the previous conversation context.
        relevance_text = f"""
        {search_context}
        {question}
        """

        # Break the user's question into words
        # that can be compared with webpage text.
        question_words = set(
            relevance_text.lower()
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
            question,
            search_context
        )

        # Use relevant webpage text when available.
        if relevant_paragraphs:

            relevant_text = "\n".join(
                relevant_paragraphs
            )
            relevant_text += f"""

            SEARCH RESULT DESCRIPTION:
            {snippet}
            """
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

    # print("\nGenerating answer...")

    conversation_context = ""

    for turn in conversation_history[-4:]:

        conversation_context += f"""
    Previous question: {turn["question"]}
    Previous answer: {turn["answer"]}
    """ 
        
    response = chat(
        model="qwen3:1.7b",

        messages=[
            {
                "role": "system",
                "content": instructions
            },
            {
            "role": "user",
            "content": f"""
        Conversation history:

        {conversation_context}

        Retrieved information:

        {source_information}

        Current question:
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

    conversation_history.append({
    "question": question,
    "answer": answer.strip()
})