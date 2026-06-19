"""Field Embeddings Seeder — Form Understanding Agent.

Seeds the `field_embeddings` table with vector representations of all canonical
profile field keys. This must be run once before the embedding-based mapping
stage can operate.

Run as a standalone script:
    python -m ai_services.form_understanding_agent.field_seeder

Or call `seed_field_embeddings(db_url)` programmatically from a Celery startup task.
"""

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical profile field registry
# All field keys that exist in profile_fields must appear here with a
# descriptive phrase to maximise embedding quality.
# ---------------------------------------------------------------------------

CANONICAL_FIELDS: List[Tuple[str, str]] = [
    ("full_name",               "Full name of the applicant"),
    ("first_name",              "First name / given name of the person"),
    ("last_name",               "Last name / family name / surname"),
    ("dob",                     "Date of birth in DD/MM/YYYY or YYYY-MM-DD format"),
    ("age",                     "Age of the applicant in years"),
    ("gender",                  "Gender of the applicant: Male, Female, or Other"),
    ("father_name",             "Father's full name"),
    ("mother_name",             "Mother's full name"),
    ("spouse_name",             "Spouse or husband or wife name"),
    ("guardian_name",           "Guardian or parent name"),
    ("aadhaar_number",          "Aadhaar card unique identification number (12 digits)"),
    ("pan_number",              "PAN card income tax permanent account number (10 characters)"),
    ("passport_number",         "Indian passport document number"),
    ("driving_license_number",  "Driving licence number issued by RTO"),
    ("voter_id",                "Voter ID card / EPIC number"),
    ("email",                   "Email address for communication"),
    ("mobile_number",           "Mobile phone number / contact number"),
    ("phone_number",            "Phone number including landline"),
    ("address_line1",           "First line of residential address, house number, street"),
    ("address_line2",           "Second line of address, locality, area, colony"),
    ("city",                    "City or town name"),
    ("district",                "District name"),
    ("state",                   "State or union territory name"),
    ("pincode",                 "Postal index number / PIN code (6 digits)"),
    ("country",                 "Country of residence"),
    ("bank_account_number",     "Bank account number for financial transactions"),
    ("bank_ifsc",               "Bank IFSC code for online transfers"),
    ("bank_name",               "Name of the bank"),
    ("annual_income",           "Annual family income in Indian Rupees"),
    ("caste",                   "Social caste category: General, OBC, SC, ST"),
    ("religion",                "Religion of the applicant"),
    ("nationality",             "Nationality of the applicant"),
    ("category",                "Reservation category: EWS, OBC, SC, ST, General"),
    ("disability_percentage",   "Percentage of disability for PwD applicants"),
    ("photograph",              "Passport size photograph of the applicant"),
    ("signature",               "Signature of the applicant"),
    ("class_10_percentage",     "10th standard board exam percentage or CGPA"),
    ("class_12_percentage",     "12th standard board exam percentage or CGPA"),
    ("graduation_percentage",   "Graduation degree percentage or CGPA"),
    ("board_10",                "Name of 10th class board (CBSE, ICSE, State)"),
    ("board_12",                "Name of 12th class board (CBSE, ICSE, State)"),
    ("passing_year_10",         "Year of passing 10th standard board examination"),
    ("passing_year_12",         "Year of passing 12th standard board examination"),
]


# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------

def seed_field_embeddings(db_sync_url: str, model_name: str = "intfloat/multilingual-e5-small") -> int:
    """Upsert canonical field embeddings into the field_embeddings table.

    Args:
        db_sync_url: Synchronous SQLAlchemy DB URL (psycopg2).
        model_name:  Sentence-transformer model to use.

    Returns:
        Number of rows upserted.
    """
    from sentence_transformers import SentenceTransformer
    from sqlalchemy import create_engine, text

    logger.info("Loading embedding model: %s", model_name)
    model = SentenceTransformer(model_name)

    # Encode with passage: prefix for asymmetric e5 models
    descriptions = [desc for _, desc in CANONICAL_FIELDS]
    logger.info("Encoding %d canonical field descriptions…", len(descriptions))
    embeddings = model.encode(
        [f"passage: {d}" for d in descriptions],
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    engine = create_engine(db_sync_url)
    upserted = 0

    with engine.begin() as conn:
        for (field_key, description), embedding in zip(CANONICAL_FIELDS, embeddings):
            vec_str = "[" + ",".join(f"{v:.6f}" for v in embedding.tolist()) + "]"
            conn.execute(
                text(
                    """
                    INSERT INTO field_embeddings (field_key, description, embedding)
                    VALUES (:key, :desc, :emb::vector)
                    ON CONFLICT (field_key) DO UPDATE
                        SET description = EXCLUDED.description,
                            embedding   = EXCLUDED.embedding
                    """
                ),
                {"key": field_key, "desc": description, "emb": vec_str},
            )
            upserted += 1

    logger.info("Seeded %d field embeddings into field_embeddings table.", upserted)
    return upserted


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import os

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Allow override via env variable (matches app config)
    db_url = os.environ.get(
        "DATABASE_SYNC_URL",
        "postgresql://autoform:autoform_secret@localhost:5432/autoformfiller",
    )
    model = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

    count = seed_field_embeddings(db_url, model)
    print(f"✓ Seeded {count} field embeddings.")
    sys.exit(0)
