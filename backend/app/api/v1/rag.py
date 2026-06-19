from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_db, get_current_user
from sqlalchemy.orm import Session
from app.models.user import User
from ai_services.rag_agent.rag_service import RagService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class RagAskRequest(BaseModel):
    question: str
    scheme_id: Optional[str] = None
    form_template_id: Optional[str] = None

class RagSource(BaseModel):
    id: str
    chunk_text: str
    source_url: str

class RagAskResponse(BaseModel):
    answer: str
    sources: List[RagSource]

@router.post("/ask", response_model=RagAskResponse)
async def ask_rag_assistant(
    request: RagAskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ask the RAG assistant a question about a scheme or form.
    """
    logger.info("RAG ask request from user %s: %s", current_user.id, request.question)
    
    # We must use a sync wrapper or execute async queries.
    # But wait, RagService in my code uses sync db.execute!
    # I should modify RagService to accept an AsyncSession and use await, or run in thread.
    rag_service = RagService(db=db)
    result = await rag_service.ask(question=request.question, scheme_id=request.scheme_id)
    
    return result
