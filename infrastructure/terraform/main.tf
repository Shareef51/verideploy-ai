provider "kubernetes" {
  host                   = var.kubernetes_host
  token                  = var.kubernetes_token
  cluster_ca_certificate = base64decode(var.kubernetes_ca_certificate_b64)
}
provider "helm" {
  kubernetes {
    host                   = var.kubernetes_host
    token                  = var.kubernetes_token
    cluster_ca_certificate = base64decode(var.kubernetes_ca_certificate_b64)
  }
}
resource "kubernetes_namespace_v1" "verideploy" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/part-of" = "verideploy-ai"
      "verideploy.ai/environment" = var.environment
    }
  }
}
resource "helm_release" "verideploy" {
  name       = "verideploy"
  namespace  = kubernetes_namespace_v1.verideploy.metadata[0].name
  chart      = "${path.module}/../helm/verideploy"
  wait       = true
  atomic     = true
  timeout    = 900
  values = [yamlencode({
    global = { environment = var.environment }
    images = {
      web     = { repository = "${var.image_registry}/verideploy-web",     tag = var.release_version }
      gateway = { repository = "${var.image_registry}/verideploy-gateway", tag = var.release_version }
      ai      = { repository = "${var.image_registry}/verideploy-ai",      tag = var.release_version }
      worker  = { repository = "${var.image_registry}/verideploy-worker",  tag = var.release_version }
    }
    canary = { gateway = { imageTag = var.release_version } }
    externalSecrets = {
      enabled        = true
      secretStoreRef = var.external_secret_store_name
      remoteKey      = var.runtime_remote_key
    }
  })]
}
