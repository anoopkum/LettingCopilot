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

variable "google_calendar_id" {
  description = "Google Calendar ID (e.g. user@gmail.com) — optional, enables real GCal bookings"
  type        = string
  sensitive   = false
  default     = ""
}

variable "google_calendar_sa_json" {
  description = "Service account JSON key for Google Calendar API — stored in Secret Manager"
  type        = string
  sensitive   = true
  default     = ""
}

variable "google_oauth_client_id" {
  description = "Google OAuth 2.0 client ID — optional, enables Google Sign-In instead of dev JWT"
  type        = string
  sensitive   = false
  default     = ""
}

variable "sendgrid_api_key" {
  description = "SendGrid API key for sending confirmation and follow-up emails"
  type        = string
  sensitive   = true
  default     = ""
}

variable "sendgrid_from_email" {
  description = "Verified sender email address in SendGrid"
  type        = string
  sensitive   = false
  default     = ""
}
