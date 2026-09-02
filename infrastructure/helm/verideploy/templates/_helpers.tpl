{{- define "verideploy.labels" -}}
app.kubernetes.io/name: verideploy
app.kubernetes.io/part-of: verideploy-ai
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
{{- define "verideploy.selectorLabels" -}}
app.kubernetes.io/name: verideploy
app.kubernetes.io/component: {{ .component }}
{{- end }}
