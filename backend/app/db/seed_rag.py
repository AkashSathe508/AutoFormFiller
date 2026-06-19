"""Seed script to populate rag_chunks with some test data."""

import asyncio
from sentence_transformers import SentenceTransformer
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.rag import RagChunk
from app.core.config import settings

def seed_rag_chunks():
    engine = create_engine(settings.DATABASE_SYNC_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    # Check if we already have chunks
    existing_count = db.query(RagChunk).count()
    if existing_count > 0:
        print(f"Database already has {existing_count} RAG chunks. Skipping seed.")
        db.close()
        return

    print("Loading embedding model...")
    model = SentenceTransformer("intfloat/multilingual-e5-small")
    
    seed_data = [
        {
            "scheme_name": "General Forms",
            "source_url": "https://india.gov.in",
            "chunk_text": "A Domicile Certificate is an official document issued by the state government to prove that a person is a resident of that state. It is primarily used to claim quota benefits in educational institutions and government jobs. Also known as a residence certificate."
        },
        {
            "scheme_name": "General Forms",
            "source_url": "https://india.gov.in",
            "chunk_text": "A Caste Certificate is a documentary proof of a person belonging to a specific caste, as listed under the Indian Constitution (SC, ST, or OBC). It is essential for availing reserved seats in educational institutions and government employment."
        },
        {
            "scheme_name": "Scholarship Portal",
            "source_url": "https://scholarships.gov.in",
            "chunk_text": "To apply for the Post-Matric Scholarship, a student must provide their Aadhaar card, income certificate (family income less than 2.5 lakhs per annum), previous year marksheet, and fee receipt of the current course."
        },
        {
            "scheme_name": "General Forms",
            "source_url": "https://uidai.gov.in",
            "chunk_text": "Aadhaar is a 12-digit unique identity number that can be obtained voluntarily by residents of India, based on their biometric and demographic data. An Aadhaar card serves as proof of identity and address, anywhere in India."
        }
    ]

    print("Seeding RAG chunks...")
    for data in seed_data:
        embedding = model.encode(f"passage: {data['chunk_text']}", normalize_embeddings=True)
        chunk = RagChunk(
            scheme_name=data["scheme_name"],
            source_url=data["source_url"],
            chunk_text=data["chunk_text"],
            embedding=embedding.tolist()
        )
        db.add(chunk)
    
    db.commit()
    db.close()
    print("Successfully seeded RAG chunks.")

if __name__ == "__main__":
    seed_rag_chunks()
