/*
  Bootstrap — run ONCE manually before anything else.
  Creates:
    - GCS bucket for remote Terraform state
    - Artifact Registry repo for Docker images
  State for bootstrap itself is local (chicken-and-egg).
*/

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

# Enable APIs needed by bootstrap and dev layers
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# GCS bucket for remote Terraform state
resource "google_storage_bucket" "tf_state" {
  name                        = "${var.project_id}-tfstate"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition { num_newer_versions = 10 }
    action    { type = "Delete" }
  }

  depends_on = [google_project_service.apis]
}

# Artifact Registry repo for Docker images
resource "google_artifact_registry_repository" "letting_copilot" {
  location      = var.region
  repository_id = "letting-copilot"
  format        = "DOCKER"
  description   = "LettingCopilot container images"
  depends_on    = [google_project_service.apis]
}

output "tf_state_bucket" {
  value       = google_storage_bucket.tf_state.name
  description = "GCS bucket for remote Terraform state"
}

output "image_repo" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/letting-copilot/letting-copilot"
  description = "Full Artifact Registry image path"
}
