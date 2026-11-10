import yake
from tenxgraph_api import ThreadNameGenerator
from tenxgraph_api.src.app.utils.thread_name_generator import DefaultThreadNameGenerator


MAX_NAME_LENGTH = 60

# YAKE: statistical keyword extraction, no model download, about 1 ms per message.
_keywords = yake.KeywordExtractor(lan="en", n=3, top=2, dedup_lim=0.7)


class MyNameGenerator(ThreadNameGenerator):
    """Names a thread after the key phrases of the customer's first message.

    "My monitor from order A-1002 arrived with a cracked screen" becomes
    "Monitor from order, cracked screen". A message with no key phrases ("Hi") gets the
    framework's random readable name.
    """

    async def generate_name(self, messages: list[str]) -> str:
        first = messages[0].strip() if messages else ""
        phrases = [phrase for phrase, _score in _keywords.extract_keywords(first)]
        if not phrases:
            return await DefaultThreadNameGenerator().generate_name(messages)
        name = ", ".join(phrases)
        name = name[0].upper() + name[1:]
        if len(name) > MAX_NAME_LENGTH:
            name = name[:MAX_NAME_LENGTH].rsplit(" ", 1)[0].rstrip(",")
        return name
