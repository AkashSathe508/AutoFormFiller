import httpx
import time
import io
import sys
from pathlib import Path

BASE_URL = "http://localhost:8000/api/v1"
FIXTURES = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"


def _synthetic_aadhaar_png() -> bytes:
    fixture = FIXTURES / "synthetic_aadhaar.png"
    if fixture.exists():
        return fixture.read_bytes()
    # Generate on the fly if fixture not yet written
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"))
    from generate_synthetic_aadhaar import build_synthetic_aadhaar_png
    return build_synthetic_aadhaar_png()


def run_test():
    print("1. Registering user...")
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        res = client.post("/auth/register", json={
            "email": "pipeline.test@example.com",
            "password": "Password123!",
            "display_name": "Pipeline Test User",
        })
        if res.status_code == 409:
            print("User already exists, proceeding to login.")
        else:
            res.raise_for_status()
            print("Registered:", res.json())

        print("2. Logging in...")
        res = client.post("/auth/login", json={
            "email": "pipeline.test@example.com",
            "password": "Password123!",
        })
        res.raise_for_status()
        access_token = res.json()["access_token"]

        print("3. Getting profiles...")
        res = client.get("/profiles", headers={"Authorization": f"Bearer {access_token}"})
        res.raise_for_status()
        profile_id = res.json()["profiles"][0]["profile_id"]
        print(f"Using profile_id: {profile_id}")

        print("4. Uploading synthetic Aadhaar image...")
        png_bytes = _synthetic_aadhaar_png()
        files = {"file": ("synthetic_aadhaar.png", io.BytesIO(png_bytes), "image/png")}
        data = {"profile_id": profile_id, "doc_type_hint": "AADHAAR"}
        res = client.post(
            "/documents",
            headers={"Authorization": f"Bearer {access_token}"},
            data=data,
            files=files,
        )
        res.raise_for_status()
        doc_id = res.json()["document_id"]
        print(f"Uploaded. Document ID: {doc_id}")

        print("5. Polling document status...")
        final_status = None
        for _ in range(30):
            res = client.get(
                f"/documents/{doc_id}/status",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            res.raise_for_status()
            status_data = res.json()
            final_status = status_data["status"]
            print(f"  status={final_status} doc_type={status_data.get('doc_type')}")
            if final_status == "failed":
                print("Pipeline failed.")
                sys.exit(1)
            if final_status == "verified":
                print("Preview fields:", status_data.get("extracted_fields_preview"))
                break
            time.sleep(3)
        else:
            print("Timeout waiting for verified status.")
            sys.exit(1)

        print("6. Reading profile fields...")
        res = client.get(
            f"/profiles/{profile_id}/fields",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"reveal": "true"},
        )
        res.raise_for_status()
        fields = res.json()["fields"]
        print(f"Profile fields ({len(fields)}):", [f["field_key"] for f in fields])
        for f in fields:
            if f["value"] == "[decryption error]":
                print(f"DECRYPTION ERROR for {f['field_key']}")
                sys.exit(1)
        print("Phase 1 pipeline OK.")
        sys.exit(0)


if __name__ == "__main__":
    run_test()
