variable "kubernetes_host" { type = string description = "Kubernetes API server URL." }
variable "kubernetes_token" { type = string sensitive = true description = "Short-lived Kubernetes bearer token supplied by the deployment environment." }
variable "kubernetes_ca_certificate_b64" { type = string sensitive = true description = "Base64-encoded cluster CA certificate." }
variable "namespace" { type = string default = "verideploy" }
variable "release_version" { type = string default = "0.86.0" }
variable "environment" { type = string default = "production" }
variable "external_secret_store_name" { type = string default = "verideploy-production" }
variable "runtime_remote_key" { type = string default = "verideploy/production/runtime" }
variable "image_registry" { type = string default = "ghcr.io/verideploy" }
