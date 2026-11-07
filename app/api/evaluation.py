from fastapi import APIRouter, HTTPException
from app.models.schemas import (
    EvaluationSTSRequest, EvaluationRougeRequest, EvaluationSentimentRequest,
)

router = APIRouter(prefix="/api", tags=["evaluation"])


@router.post("/get_sts_score")
def get_sts_score(payload: EvaluationSTSRequest):
    try:
        # Keep the model import lazy: sentence-transformers/torch are large
        # optional dependencies and should not slow API startup.
        from sentence_transformers import SentenceTransformer, util
        model = SentenceTransformer("paraphrase-distilroberta-base-v2")
        q_embedding = model.encode(payload.query, convert_to_tensor=True)
        r_embedding = model.encode(payload.response, convert_to_tensor=True)
        score = util.pytorch_cos_sim(q_embedding, r_embedding).item()
        return {"sts_score": str(score)}
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Install requirements-evaluation.txt to enable STS evaluation.") from exc


@router.post("/get_rouge_score")
def get_rouge_score(payload: EvaluationRougeRequest):
    try:
        from rouge_score import rouge_scorer
        scorer = rouge_scorer.RougeScorer(["rouge1"], use_stemmer=True)
        score = scorer.score(payload.reference, payload.response)["rouge1"]
        return {
            "RougeN_Precission": score.precision,
            "RougeN_Recall": score.recall,
            "RougeN_Fmessure": score.fmeasure,
        }
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Install requirements-evaluation.txt to enable ROUGE evaluation.") from exc


@router.post("/get_sentiment_analysis")
def get_sentiment_analysis(payload: EvaluationSentimentRequest):
    try:
        from transformers import pipeline
        classifier = pipeline("sentiment-analysis")
        result = classifier(payload.query + " " + payload.response)[0]
        return {"sentiment_label": result["label"], "sentiment_score": result["score"]}
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Install requirements-evaluation.txt to enable sentiment analysis.") from exc
