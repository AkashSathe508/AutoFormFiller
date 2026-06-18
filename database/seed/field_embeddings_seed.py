#!/usr/bin/env python3
"""
field_embeddings_seed.py

Generates e5-small embeddings for all canonical profile field keys
and inserts them into the field_embeddings table.

Run once after schema creation:
    python database/seed/field_embeddings_seed.py
"""

import os
import sys
import json
import psycopg2
from sentence_transformers import SentenceTransformer

# Canonical profile fields with human-readable descriptions for embedding
CANONICAL_FIELDS = [
    {"key": "full_name", "description": "Full legal name of the person"},
    {"key": "first_name", "description": "First name / given name"},
    {"key": "last_name", "description": "Last name / surname / family name"},
    {"key": "middle_name", "description": "Middle name"},
    {"key": "father_name", "description": "Father's name / name of father"},
    {"key": "mother_name", "description": "Mother's name / name of mother"},
    {"key": "spouse_name", "description": "Spouse name / husband name / wife name"},
    {"key": "dob", "description": "Date of birth / birth date / DOB / जन्म तिथि"},
    {"key": "age", "description": "Age in years"},
    {"key": "gender", "description": "Gender / sex / male or female"},
    {"key": "aadhaar_number", "description": "Aadhaar card number / UID / unique identification number (12 digits)"},
    {"key": "pan_number", "description": "PAN card number / permanent account number / income tax PAN"},
    {"key": "passport_number", "description": "Passport number / travel document number"},
    {"key": "driving_license_number", "description": "Driving license number / DL number"},
    {"key": "voter_id", "description": "Voter ID number / election card number / EPIC number"},
    {"key": "address_line1", "description": "Address line 1 / house number / flat number / building name"},
    {"key": "address_line2", "description": "Address line 2 / street / colony / locality"},
    {"key": "city", "description": "City / town / district headquarters"},
    {"key": "district", "description": "District / taluka / tehsil"},
    {"key": "state", "description": "State / province / राज्य"},
    {"key": "pincode", "description": "Pincode / PIN code / postal code / zip code"},
    {"key": "country", "description": "Country / देश"},
    {"key": "mobile_number", "description": "Mobile number / phone number / contact number"},
    {"key": "email", "description": "Email address / email ID"},
    {"key": "nationality", "description": "Nationality / citizenship / राष्ट्रीयता"},
    {"key": "religion", "description": "Religion / धर्म"},
    {"key": "caste", "description": "Caste / जाति"},
    {"key": "caste_category", "description": "Category / caste category / SC / ST / OBC / General / EWS"},
    {"key": "annual_income", "description": "Annual income / yearly income / family income / वार्षिक आय"},
    {"key": "income_certificate_number", "description": "Income certificate number"},
    {"key": "caste_certificate_number", "description": "Caste certificate number / जाति प्रमाण पत्र संख्या"},
    {"key": "domicile_state", "description": "Domicile state / state of domicile / मूल निवास राज्य"},
    {"key": "domicile_certificate_number", "description": "Domicile certificate number"},
    {"key": "blood_group", "description": "Blood group / blood type / रक्त समूह"},
    {"key": "disability_status", "description": "Disability status / whether disabled / PwD"},
    {"key": "disability_percentage", "description": "Percentage of disability"},
    {"key": "disability_certificate_number", "description": "Disability certificate number / PwD certificate"},
    {"key": "bank_account_number", "description": "Bank account number / account number / खाता संख्या"},
    {"key": "bank_ifsc", "description": "IFSC code / bank IFSC / bank branch code"},
    {"key": "bank_name", "description": "Bank name / बैंक का नाम"},
    {"key": "bank_branch", "description": "Bank branch / branch name"},
    {"key": "tenth_percentage", "description": "10th class percentage / SSC marks / matriculation percentage"},
    {"key": "tenth_year", "description": "10th class passing year / SSC year"},
    {"key": "tenth_board", "description": "10th class board / SSC board / CBSE / ICSE / state board"},
    {"key": "tenth_rollno", "description": "10th class roll number / SSC roll number"},
    {"key": "twelfth_percentage", "description": "12th class percentage / HSC marks / intermediate percentage"},
    {"key": "twelfth_year", "description": "12th class passing year / HSC year"},
    {"key": "twelfth_board", "description": "12th class board / HSC board"},
    {"key": "twelfth_rollno", "description": "12th class roll number"},
    {"key": "twelfth_stream", "description": "12th class stream / science / arts / commerce"},
    {"key": "graduation_percentage", "description": "Graduation percentage / bachelor's degree marks / CGPA"},
    {"key": "graduation_year", "description": "Graduation passing year"},
    {"key": "graduation_university", "description": "University / college / institution name"},
    {"key": "graduation_course", "description": "Graduation course / degree / bachelor of"},
    {"key": "current_occupation", "description": "Current occupation / job / profession / employment status"},
    {"key": "employer_name", "description": "Employer name / company name / organization"},
    {"key": "photo_filename", "description": "Passport photo / photograph / profile photo"},
    {"key": "signature_filename", "description": "Signature / sign / हस्ताक्षर"},
]

def main():
    db_url = os.environ.get(
        "DATABASE_SYNC_URL",
        "postgresql://autoform:autoform_secret@localhost:5432/autoformfiller"
    )

    print(f"Loading embedding model...")
    model = SentenceTransformer("intfloat/multilingual-e5-small")
    print(f"Model loaded. Generating embeddings for {len(CANONICAL_FIELDS)} fields...")

    texts = [f['description'] for f in CANONICAL_FIELDS]
    embeddings = model.encode(texts, normalize_embeddings=True)

    print("Connecting to database...")
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    inserted = 0
    for field, embedding in zip(CANONICAL_FIELDS, embeddings):
        embedding_list = embedding.tolist()
        cur.execute("""
            INSERT INTO field_embeddings (field_key, description, embedding)
            VALUES (%s, %s, %s::vector)
            ON CONFLICT (field_key) DO UPDATE
            SET description = EXCLUDED.description,
                embedding = EXCLUDED.embedding
        """, (field['key'], field['description'], str(embedding_list)))
        inserted += 1
        print(f"  [{inserted}/{len(CANONICAL_FIELDS)}] {field['key']}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone! Inserted/updated {inserted} field embeddings.")

if __name__ == "__main__":
    main()
