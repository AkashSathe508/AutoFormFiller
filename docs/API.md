# AutoFormFiller API Documentation

Base URL: `http://localhost:8000/api/v1`

All endpoints (except `/auth/*`) require:
```
Authorization: Bearer <access_token>
```

## Authentication

### POST /auth/register
Register a new user account.

**Request:**
```json
{
  "email": "user@example.com",
  "phone": "+919876543210",
  "password": "strongpassword123!"
}
```
**Response 201:**
```json
{"user_id": "uuid", "message": "Verification OTP sent to phone"}
```

### POST /auth/login
```json
// Request
{"email": "user@example.com", "password": "..."}
// Response 200
{"access_token": "jwt", "refresh_token": "jwt", "expires_in": 900}
```

### POST /auth/refresh
Refresh access token using refresh_token.

## Profiles

### POST /profiles
Create a new profile (self or family member).

### GET /profiles/{id}/fields
Get all extracted profile fields.

### DELETE /profiles/{id}
Right-to-erasure (DPDP). Destroys DEK, schedules doc purge.

### GET /profiles/{id}/export
Data portability export (JSON or PDF).

## Documents

### POST /documents
Upload a document (multipart). Max 15MB. JPEG/PNG/PDF only.

### GET /documents/{id}/status
Get processing status and extracted fields preview.

### GET /documents
List vault contents for a profile.

## Forms

### POST /forms
Submit a form URL or PDF upload for parsing.

### POST /forms/{template_id}/fill
Start auto-fill for a profile against a parsed form.

### POST /forms/instances/{id}/gap-fill
Provide values for unmapped fields.

### GET /forms/instances/{id}/review
Get the review screen data (all fields, confidence, method, warnings).

### POST /forms/instances/{id}/confirm
Confirm reviewed form (must acknowledge all flagged fields).

### POST /forms/instances/{id}/submit
Submit the confirmed form.

## Applications

### GET /applications
List all applications with status.

### PATCH /applications/{id}/status
Manually update application status.
