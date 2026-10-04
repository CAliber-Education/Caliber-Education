from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_service_key: str

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # Razorpay
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""

    # Cloudflare Turnstile
    turnstile_secret_key: str = ""

    # SendGrid
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@calibereducation.com"

    # Where contact-form submissions are forwarded — swap this once you have
    # a real support inbox
    contact_notification_email: str = "adarshguptaa1108@gmail.com"

    # Groq (free-tier LLM) — powers "Import from PDF" in the MCQ editor.
    # Read from GROQ_API_KEY; without it that one feature reports itself
    # unavailable and everything else works as normal.
    groq_api_key: str = ""

    # Supabase Storage Buckets
    supabase_submission_bucket: str = "test-submissions"
    supabase_evaluation_bucket: str = "evaluated-papers"
    supabase_test_series_bucket: str = "test-series-papers"

    # App
    frontend_url: str = "http://localhost:3000"
    # Fail closed: missing/unset APP_ENV must behave like production, not
    # skip auth/bot-check/OTP safeguards. Set APP_ENV=development explicitly
    # in your local .env to opt into dev conveniences.
    app_env: str = "production"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
