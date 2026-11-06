"""Stable sentence-sized evidence units, retaining offsets into the article."""
import re

# Titles and common abbreviations whose period normally does not end a sentence.
_ABBREVIATIONS = {'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs',
                  'e.g', 'i.e', 'no', 'fig'}
_END = re.compile(r'''[.!?。！？]+["'”’）)\]]*(?=\s|$)|[。！？]+["'”’）)\]]*''')


def split_article_sentences(content):
    """Split at sentence punctuation/paragraph boundaries without rewriting text."""
    rows = []

    def append(start, end, paragraph_index):
        while start < end and content[start].isspace():
            start += 1
        while end > start and content[end - 1].isspace():
            end -= 1
        if start < end:
            rows.append(dict(index=len(rows), text=content[start:end],
                             paragraph_index=paragraph_index,
                             start_offset=start, end_offset=end))

    paragraphs = list(re.finditer(r'\S(?:.*?\S)?(?=\n\s*\n|$)', content, re.DOTALL))
    for paragraph_index, paragraph in enumerate(paragraphs):
        text = paragraph.group()
        cursor = 0
        for match in _END.finditer(text):
            end = match.end()
            if match.group().startswith('.'):
                token_match = re.search(r'([A-Za-z][A-Za-z.]*)\.$', text[:match.start()+1])
                token = token_match.group(1) if token_match else ''
                following = text[end:].lstrip()
                if following and (token.lower() in _ABBREVIATIONS
                                  or re.fullmatch(r'[A-Z]', token)
                                  or (re.fullmatch(r'(?:[A-Za-z]\.)+[A-Za-z]', token)
                                      and following[0].islower())):
                    continue
            append(paragraph.start()+cursor, paragraph.start()+end, paragraph_index)
            cursor = end
        append(paragraph.start()+cursor, paragraph.end(), paragraph_index)
    return rows
