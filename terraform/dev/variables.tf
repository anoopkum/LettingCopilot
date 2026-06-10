variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "gemini_api_key" {
  description = "Gemini API key — stored in Secret Manager, never logged"
  type        = string
  sensitive   = true
}

variable "jwt_secret" {
  description = "HS256 JWT signing secret — stored in Secret Manager, never logged"
  type        = string
  sensitive   = true
  default     = "lettingcopilot-dev-secret-change-in-prod"
}
