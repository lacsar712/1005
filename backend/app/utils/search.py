def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    s1 = s1.lower()
    s2 = s2.lower()
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def fuzzy_match(query, text, max_distance=2):
    if not query or not text:
        return False
    q = query.lower().strip()
    t = text.lower()
    if not q:
        return False
    if q in t:
        return True
    words = t.split()
    for word in words:
        word_clean = word.strip(' ,.;:!?()[]{}"\'')
        if not word_clean:
            continue
        if q in word_clean:
            return True
        word_len = len(word_clean)
        query_len = len(q)
        if word_len < 3 or query_len < 3:
            continue
        allowed = max_distance if max(word_len, query_len) >= 5 else 1
        if levenshtein_distance(q, word_clean) <= allowed:
            return True
    return False


def highlight_keywords(text, query):
    if not text or not query:
        return text or ''
    q = query.strip()
    if not q:
        return text
    q_lower = q.lower()
    text_lower = text.lower()
    result = []
    i = 0
    used = set()
    while i < len(text):
        matched = False
        for length in range(min(len(q) + 3, len(text) - i), max(1, len(q) - 3), -1):
            if length <= 0:
                continue
            segment = text_lower[i:i + length]
            if q_lower in segment:
                idx = segment.find(q_lower)
                result.append(text[i:i + idx])
                result.append(f'<mark class="bg-yellow-200 text-yellow-900 px-0.5 rounded">{text[i + idx:i + idx + len(q)]}</mark>')
                i += idx + len(q)
                matched = True
                break
            if levenshtein_distance(q_lower, segment) <= 2 and length >= 3:
                result.append(f'<mark class="bg-yellow-100 text-yellow-800 px-0.5 rounded border border-yellow-300">{text[i:i + length]}</mark>')
                i += length
                matched = True
                break
        if not matched:
            result.append(text[i])
            i += 1
    return ''.join(result)
