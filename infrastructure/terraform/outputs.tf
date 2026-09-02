output "namespace" { value = kubernetes_namespace_v1.verideploy.metadata[0].name }
output "helm_release" { value = helm_release.verideploy.name }
output "release_version" { value = var.release_version }
