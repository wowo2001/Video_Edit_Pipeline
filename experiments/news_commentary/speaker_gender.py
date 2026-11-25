"""Keep reusable voice gender results alongside transcript speaker attributes."""
def mapping_from_transcript(transcript):
    result = {}
    for row in transcript.get('utterances', []):
        attr = row.get('attribute', {})
        speaker, gender = attr.get('speaker'), attr.get('gender')
        if speaker and speaker != 'UNKNOWN' and gender in ('male', 'female'):
            result[speaker] = {'gender': gender, 'confidence': attr.get('gender_confidence')}
    return result


def attach_genders(transcript, mapping):
    for row in transcript.get('utterances', []):
        attr = row.setdefault('attribute', {})
        value = mapping.get(attr.get('speaker'), {})
        if value.get('gender') in ('male', 'female'):
            attr.update(gender=value['gender'], gender_confidence=value.get('confidence'))
    return transcript

