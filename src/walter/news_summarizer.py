import logging
import re
import numpy as np
from collections import defaultdict
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_similarity
import html
from walter.config import SENTENCE_TRANSFORMER_MODEL, EPS

logger = logging.getLogger(__name__)

# Load the model once at module level to avoid reloading on every call
_sentence_model = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL)


def get_summaries_from_news(all_news):
    """Cluster news articles into major narratives and secondary signals."""
    cleaned_texts = []
    clickbait = ["heres", "could", "might", "skyrocket", "why", "what happened"]

    for n in all_news:
        # We include the body because narratives are found in the details
        text = f"{n.get('title', '')} {n.get('body', '')[:200]}".lower()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = html.unescape(text)
        for word in clickbait:
            text = text.replace(word, "")
        cleaned_texts.append(re.sub(r"\s+", " ", text).strip())

    # Embed & cluster (high EPS = broad narratives)
    embeddings = _sentence_model.encode(cleaned_texts, normalize_embeddings=True)

    # eps is the "Narrative Threshold" — it groups by general topic
    clustering = DBSCAN(eps=EPS, min_samples=2, metric="cosine")
    labels = clustering.fit_predict(embeddings)

    # Organize by narrative
    narratives = defaultdict(list)
    for i, lab in enumerate(labels):
        narratives[lab].append(i)

    # Generate the summary
    logger.info("=== SUMMARIZING MARKET NARRATIVES ===")
    items = sorted(narratives.items(), key=lambda x: (x[0] == -1, -len(x[1])))

    result = {
        "major_narratives": [],
        "secondary_signals": [],
    }

    for lab, idxs in items:
        if lab == -1:
            # Secondary signals: one per article
            for i in idxs:
                title = all_news[i].get("title", "") or "Untitled"
                body = all_news[i].get("body", "")
                result["secondary_signals"].append(
                    {
                        "title": f"[Secondary Signal] {title} #{i}",
                        "body": body,
                        "source_count": 1,
                    }
                )
            continue

        # Representative (most central) item in the cluster
        sub_embeddings = embeddings[idxs]
        sim_matrix = cosine_similarity(sub_embeddings, sub_embeddings)
        best_local = int(np.argmax(sim_matrix.mean(axis=1)))
        best_idx = int(idxs[best_local])

        count = int(len(idxs))
        lab_py = int(lab)  # ensure Python int (DBSCAN label)
        title = all_news[best_idx].get("title", "") or "Untitled"
        body = all_news[best_idx].get("body", "")

        result["major_narratives"].append(
            {
                "title": f"[{count} sources] {title} #{lab_py}",
                "body": body,
                "source_count": count,
            }
        )

    return result
