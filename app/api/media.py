from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter(prefix="/api", tags=["media"])


@router.post("/get_transcript")
async def get_transcript(audio: UploadFile = File(...)):
    """Accept audio uploaded by the client.

    The old implementation tried to record audio from the server's microphone.
    That will not work in ECS: a container cannot access an employee's laptop
    microphone. This endpoint will be connected to Amazon Transcribe later.
    """
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Upload an audio file.")
    raise HTTPException(status_code=501, detail="Amazon Transcribe integration is planned for a later phase.")


@router.post("/record_voice")
async def record_voice(audio: UploadFile = File(...)):
    """Compatibility route: clients upload a recording; the server does not record audio."""
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="Upload an audio file.")
    raise HTTPException(status_code=501, detail="Audio upload is accepted by the API contract; transcription is not connected yet.")


@router.post("/image_analysis")
async def image_analysis(image: UploadFile = File(...), query: str = ""):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Upload an image file.")
    raise HTTPException(status_code=501, detail="Bedrock multimodal image analysis is planned for a later phase.")
