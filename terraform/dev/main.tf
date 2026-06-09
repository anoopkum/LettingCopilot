terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "aiplatform.googleapis.com",
    "firestore.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# Artifact Registry for Docker images
resource "google_artifact_registry_repository" "ava" {
  location      = var.region
  repository_id = "letting-copilot"
  format        = "DOCKER"
  description   = "LettingCopilot container images"
  depends_on    = [google_project_service.apis]
}

# Service account for Cloud Run
resource "google_service_account" "letting_copilot_runner" {
  account_id   = "letting-copilot-runner"
  display_name = "Ava Lettings Cloud Run SA"
}

resource "google_project_iam_member" "ava_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.letting_copilot_runner.email}"
}

resource "google_project_iam_member" "ava_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.letting_copilot_runner.email}"
}

# Cloud Run service
resource "google_cloud_run_v2_service" "ava" {
  name     = "letting-copilot"
  location = var.region

  template {
    service_account = google_service_account.letting_copilot_runner.email

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/letting-copilot/letting-copilot:${var.image_tag}"

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }
      env {
        name  = "ENVIRONMENT"
        value = "dev"
      }
      env {
        name  = "AVA_MODEL"
        value = "gemini-2.0-flash-001"
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

  depends_on = [google_project_service.apis]
}

# Allow unauthenticated access for POC/dev
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = google_cloud_run_v2_service.ava.project
  location = google_cloud_run_v2_service.ava.location
  name     = google_cloud_run_v2_service.ava.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "service_url" {
  value       = google_cloud_run_v2_service.ava.uri
  description = "Cloud Run service URL"
}

output "image_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/letting-copilot/letting-copilot"
}
