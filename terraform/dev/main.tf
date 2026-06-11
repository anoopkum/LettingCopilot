/*
  Dev environment — Cloud Run + IAM + Secret Manager
  Remote state stored in GCS (bucket created by bootstrap layer).
*/

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "gen-lang-client-0300667287-tfstate"
    prefix = "letting-copilot/dev"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ── Secret Manager: Gemini API key ────────────────────────────────────────────
resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "gemini-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "gemini_api_key" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = var.gemini_api_key
}

# ── Secret Manager: JWT signing secret ───────────────────────────────────────
resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "jwt-secret"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "jwt_secret" {
  secret      = google_secret_manager_secret.jwt_secret.id
  secret_data = var.jwt_secret
}

# ── Secret Manager: SendGrid API key ─────────────────────────────────────────
resource "google_secret_manager_secret" "sendgrid_api_key" {
  secret_id = "sendgrid-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "sendgrid_api_key" {
  secret      = google_secret_manager_secret.sendgrid_api_key.id
  secret_data = var.sendgrid_api_key != "" ? var.sendgrid_api_key : "not-configured"
}

# ── Secret Manager: Pinecone API key ─────────────────────────────────────────
resource "google_secret_manager_secret" "pinecone_api_key" {
  secret_id = "pinecone-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "pinecone_api_key" {
  secret      = google_secret_manager_secret.pinecone_api_key.id
  secret_data = var.pinecone_api_key != "" ? var.pinecone_api_key : "not-configured"
}

# ── Secret Manager: Google Calendar service account JSON ─────────────────────
# Always created; stores "{}" placeholder when calendar not configured.
# Python checks for required SA key fields and falls back to mock if not present.
resource "google_secret_manager_secret" "calendar_sa_json" {
  secret_id = "calendar-sa-json"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "calendar_sa_json" {
  secret      = google_secret_manager_secret.calendar_sa_json.id
  secret_data = var.google_calendar_sa_json != "" ? var.google_calendar_sa_json : "{}"
}

# ── Service account for Cloud Run ─────────────────────────────────────────────
resource "google_service_account" "runner" {
  account_id   = "letting-copilot-runner"
  display_name = "LettingCopilot Cloud Run SA"
}

resource "google_project_iam_member" "runner_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.runner.email}"
}

resource "google_project_iam_member" "runner_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runner.email}"
}

# ── Cloud Run service ─────────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "letting_copilot" {
  name     = "letting-copilot"
  location = var.region

  template {
    service_account = google_service_account.runner.email
    timeout         = "300s"

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/letting-copilot/letting-copilot:${var.image_tag}"

      ports {
        container_port = 8080
      }

      env {
        name  = "ENVIRONMENT"
        value = "dev"
      }
      env {
        name  = "AVA_MODEL"
        value = "gemini-flash-latest"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "false"
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_GENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret.secret_id
            version = "latest"
          }
        }
      }

      # Google Calendar — empty GOOGLE_CALENDAR_ID triggers mock fallback in Python
      env {
        name  = "GOOGLE_CALENDAR_ID"
        value = var.google_calendar_id
      }
      env {
        name = "GOOGLE_CALENDAR_SA_JSON"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.calendar_sa_json.secret_id
            version = "latest"
          }
        }
      }
      # Google OAuth — empty string means dev JWT mode
      env {
        name  = "GOOGLE_OAUTH_CLIENT_ID"
        value = var.google_oauth_client_id
      }

      # SendGrid email notifications
      env {
        name = "SENDGRID_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.sendgrid_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "SENDGRID_FROM_EMAIL"
        value = var.sendgrid_from_email
      }

      # Pinecone vector property search
      env {
        name = "PINECONE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.pinecone_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "PINECONE_INDEX"
        value = var.pinecone_index
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 10
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
  }

  depends_on = [
    google_project_iam_member.runner_secret_accessor,
    google_secret_manager_secret_version.gemini_api_key,
    google_secret_manager_secret_version.jwt_secret,
    google_secret_manager_secret_version.calendar_sa_json,
    google_secret_manager_secret_version.sendgrid_api_key,
    google_secret_manager_secret_version.pinecone_api_key,
  ]
}

# ── Public access (POC/dev — no auth) ────────────────────────────────────────
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = google_cloud_run_v2_service.letting_copilot.project
  location = google_cloud_run_v2_service.letting_copilot.location
  name     = google_cloud_run_v2_service.letting_copilot.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "service_url" {
  value       = google_cloud_run_v2_service.letting_copilot.uri
  description = "Live Cloud Run URL"
}

output "image_repo" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/letting-copilot/letting-copilot"
  description = "Artifact Registry image path"
}

output "service_account" {
  value       = google_service_account.runner.email
  description = "Cloud Run service account email"
}
