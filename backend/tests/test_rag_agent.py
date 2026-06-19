import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from app.models.rag import RagChunk
from ai_services.rag_agent.rag_service import RagService

@pytest_asyncio.fixture
async def mock_rag_db(async_db_session):
    # Add a mock chunk
    chunk = RagChunk(
        scheme_name="Test Scheme",
        source_url="http://test.gov.in",
        chunk_text="A mock domicile certificate is a test document.",
        # Provide a dummy 384-dim vector
        embedding=[0.1] * 384 
    )
    async_db_session.add(chunk)
    await async_db_session.flush()
    return async_db_session

@pytest.mark.asyncio
async def test_rag_service_embed_and_retrieve(mock_rag_db):
    service = RagService(db=mock_rag_db)
    
    # Mock embedding to avoid loading real sentence-transformer in test
    service._embed_model = MagicMock()
    # Return a dummy vector close to the inserted one
    mock_vec = MagicMock()
    mock_vec.tolist.return_value = [0.1] * 384
    service._embed_model.encode.return_value = mock_vec

    # Test embed
    vec = service._embed_question("What is a domicile certificate?")
    assert len(vec) == 384
    
    # Test retrieve
    chunks = await service._retrieve_context(vec, limit=2)
    assert len(chunks) >= 1
    assert "mock domicile certificate" in chunks[0]["chunk_text"]
    assert chunks[0]["score"] > 0.9  # Should be very close to 1.0

@pytest.mark.asyncio
@patch("ai_services.rag_agent.rag_service.httpx.AsyncClient")
async def test_rag_service_generate_answer(mock_client_cls, mock_rag_db):
    service = RagService(db=mock_rag_db)
    
    # Mock Ollama response
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "A mock domicile certificate is a test document."}
    mock_response.raise_for_status.return_value = None
    
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    
    chunks = [{"id": "uuid1", "chunk_text": "A mock domicile certificate is a test document.", "source_url": "url"}]
    answer = await service._generate_answer("What is it?", chunks)
    
    assert answer == "A mock domicile certificate is a test document."
    
    # Verify the prompt contained the chunk
    call_args = mock_client.post.call_args
    assert call_args is not None
    json_payload = call_args[1]["json"]
    assert "A mock domicile certificate is a test document." in json_payload["prompt"]
    assert "What is it?" in json_payload["prompt"]

@pytest.mark.asyncio
@patch("ai_services.rag_agent.rag_service.httpx.AsyncClient")
async def test_rag_service_ask_end_to_end(mock_client_cls, mock_rag_db):
    service = RagService(db=mock_rag_db)
    service._embed_model = MagicMock()
    mock_vec = MagicMock()
    mock_vec.tolist.return_value = [0.1] * 384
    service._embed_model.encode.return_value = mock_vec

    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "Based on Source 1, it's a test document."}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    result = await service.ask("What is a domicile certificate?")
    
    assert "answer" in result
    assert "sources" in result
    assert result["answer"] == "Based on Source 1, it's a test document."
    assert len(result["sources"]) >= 1
    assert result["sources"][0]["source_url"] == "http://test.gov.in"
