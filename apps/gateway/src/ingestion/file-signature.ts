import { BadRequestException } from "@nestjs/common";
import { createReadStream } from "node:fs";

export async function detectMime(path:string): Promise<string> {
  const stream=createReadStream(path,{start:0,end:31}); const chunks:Buffer[]=[];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk)); const b=Buffer.concat(chunks);
  if (b.subarray(0,5).toString()==="%PDF-") return "application/pdf";
  if (b[0]===0x89 && b.subarray(1,4).toString()==="PNG") return "image/png";
  if (b[0]===0xff && b[1]===0xd8 && b[2]===0xff) return "image/jpeg";
  if (b.subarray(0,4).toString()==="RIFF" && b.subarray(8,12).toString()==="WEBP") return "image/webp";
  if (b.subarray(0,4).toString()==="RIFF" && b.subarray(8,12).toString()==="WAVE") return "audio/wav";
  if (b.subarray(0,3).toString()==="ID3" || (b[0]===0xff && ((b[1]??0)&0xe0)===0xe0)) return "audio/mpeg";
  if (b.length>=12 && b.subarray(4,8).toString()==="ftyp") {
    const brand=b.subarray(8,12).toString(); if (["M4A ","M4B ","mp42","isom"].includes(brand)) return brand.startsWith("M4") ? "audio/mp4" : "video/mp4"; return "video/mp4";
  }
  const text=b.toString("utf8"); const printable=[...b].every((value)=>value===9||value===10||value===13||(value>=32&&value<=126)); if (printable && text.length>0) return "text/plain";
  throw new BadRequestException({code:"UNSUPPORTED_FILE_SIGNATURE",message:"File content does not match an allowed type"});
}
export function assertModality(modality:string,mime:string):void {
  const allowed:Record<string,string[]>={document:["application/pdf","text/plain"],image:["image/png","image/jpeg","image/webp"],audio:["audio/wav","audio/mpeg","audio/mp4"],video:["video/mp4"]};
  if (!allowed[modality]?.includes(mime)) throw new BadRequestException({code:"MIME_MODALITY_MISMATCH",message:`Detected ${mime} is not valid for ${modality}`});
}
