export type Modality = "document" | "image" | "audio" | "video";
export type IngestionAccepted = { job_id:string; correlation_id:string; status:"QUEUED"; detected_mime_type:string; sha256:string; size_bytes:number; authoritative:false };
export type CreateUploadHandoffRequest={modality:Modality;filename:string;content_type:string;size_bytes:number;sha256:string};
export type CompleteUploadHandoffRequest={modality:Modality;filename:string;content_type:string;size_bytes:number;sha256:string};
