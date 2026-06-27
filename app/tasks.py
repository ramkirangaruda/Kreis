"""Background tasks (Celery)."""

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.ocr import extract_text_bhashini
from app.models.document import UploadedDocument, OcrStatus


@celery_app.task(name="app.tasks.process_ocr")
def process_ocr(document_id: int, file_path: str):
    """Extract OCR text for an uploaded document and update its record.

    Each task runs in its own event loop (asyncio.run), so it must NOT reuse
    the app's shared connection pool — those asyncpg connections are bound to
    a different loop. We build a throwaway NullPool engine per invocation and
    dispose it at the end.
    """

    async def run():
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with Session() as db:
                doc = await db.get(UploadedDocument, document_id)
                if not doc:
                    return

                doc.ocr_status = OcrStatus.PROCESSING
                await db.commit()

                text = await extract_text_bhashini(file_path)

                doc.ocr_text = text
                doc.ocr_status = (
                    OcrStatus.FAILED if text.startswith("[") else OcrStatus.DONE
                )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())
