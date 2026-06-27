"""Kannada OCR via the Bhashini API.

If BHASHINI_API_KEY is not configured the function returns a placeholder so
the rest of the system keeps working without the credentials.
"""

import base64

import httpx

from app.core.config import settings

BHASHINI_PIPELINE_URL = (
    "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
)


async def extract_text_bhashini(file_path: str) -> str:
    """Call the Bhashini OCR pipeline to extract Kannada/English text from an image.

    Returns the extracted text on success, or a bracketed ``[...]`` status
    string on any failure (callers treat a leading ``[`` as a failure marker).
    """
    if not settings.bhashini_api_key:
        return "[OCR not configured — add BHASHINI_API_KEY to .env]"

    try:
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
    except OSError as exc:
        return f"[OCR failed — could not read file: {exc}]"

    payload = {
        "pipelineTasks": [
            {
                "taskType": "ocr",
                "config": {
                    "language": {"sourceLanguage": "kn"},
                    "serviceId": "",
                },
            }
        ],
        "inputData": {
            "input": [{"source": encoded}],
            "audio": [],
        },
    }

    headers = {
        "userID": settings.bhashini_user_id,
        "ulcaApiKey": settings.bhashini_api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                BHASHINI_PIPELINE_URL, json=payload, headers=headers
            )
    except httpx.HTTPError as exc:
        return f"[OCR failed — request error: {exc}]"

    if response.status_code != 200:
        return f"[OCR failed — status {response.status_code}]"

    try:
        data = response.json()
        return data["pipelineResponse"][0]["output"][0]["source"]
    except (KeyError, IndexError, ValueError):
        return "[OCR extraction failed — unexpected response format]"
