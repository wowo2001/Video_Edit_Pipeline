"""Use provider subtitle words and paragraph boundaries directly."""


def paragraph_times(sentences):
    groups = [[]]
    for sentence in sentences:
        groups[-1].extend(dict(text=w['word'], start=w['startTime'], end=w['endTime'])
                          for w in sentence['words'])
        # Input parts are separated by newlines, retained in sentence.text.
        if '\n' in sentence['text']:
            groups.append([])
    return [group for group in groups if group]
