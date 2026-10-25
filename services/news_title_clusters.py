"""Local title grouping using the existing embedding service and clustering method."""
import numpy as np
from sklearn.cluster import AgglomerativeClustering


def group_titles(items, embeddings, similarity=0.8):
    if not items:
        return []
    vectors = np.asarray(embeddings, dtype=float)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    labels = (AgglomerativeClustering(n_clusters=None, metric='cosine', linkage='average',
                                     distance_threshold=1-similarity).fit_predict(vectors)
              if len(items) > 1 else np.array([0]))
    groups = []
    for label in sorted(set(labels)):
        core = np.flatnonzero(labels == label)
        centroid = vectors[core].mean(axis=0)
        centroid /= max(np.linalg.norm(centroid), 1e-12)
        scores = vectors @ centroid
        members = sorted(set(core.tolist()) | set(np.flatnonzero(scores >= similarity).tolist()))
        representative = int(core[np.argmax(scores[core])])
        groups.append({'title': items[representative]['title'],
                       'items': [items[i] for i in members]})
    # Identical memberships need only one box; partial overlaps remain visible.
    unique = {}
    for group in groups:
        key = tuple(sorted(item['video_id'] for item in group['items']))
        unique.setdefault(key, group)
    return sorted(unique.values(), key=lambda g: -len(g['items']))
