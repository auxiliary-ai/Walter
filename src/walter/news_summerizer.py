import re
import numpy as np
from collections import defaultdict
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_similarity
import html
from dotenv import load_dotenv
import os

for dotenv_file in (".env.local", ".env"):
    load_dotenv(dotenv_path=dotenv_file, override=False)

SENTENCE_TRANSFORMER_MODEL = os.getenv("SENTENCE_TRANSFORMER_MODEL")
EPS = float(os.getenv("EPS"))


def get_summaries_from_news(all_news):
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

    # 3. EMBED & CLUSTER (High EPS = Broad Narratives)

    model = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL)
    embeddings = model.encode(cleaned_texts, normalize_embeddings=True)

    # eps is the "Narrative Threshold" - it groups by general topic
    clustering = DBSCAN(eps=EPS, min_samples=2, metric="cosine")
    labels = clustering.fit_predict(embeddings)

    # 4. ORGANIZE BY NARRATIVE
    narratives = defaultdict(list)
    for i, lab in enumerate(labels):
        narratives[lab].append(i)

    # 5. GENERATE THE SUMMARY
    print("=== SUMMERIZING MARKET NARRATIVES ===")
    items = sorted(narratives.items(), key=lambda x: (x[0] == -1, -len(x[1])))

    result = {
        "major_narratives": [],  # easy filter
        "secondary_signals": [],  # easy filter
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

        # representative (most central) item in the cluster
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
