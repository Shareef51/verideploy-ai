import { createHash, createPublicKey, randomBytes, verify } from "node:crypto";
import { get as httpsGet } from "node:https";

export type AuthContext={subject:string;tenantId:string;roles:string[];attributes:Record<string,string>};
type Jwk={kid?:string;kty:string;n?:string;e?:string;alg?:string;use?:string};

function b64urlJson(value:string){return JSON.parse(Buffer.from(value,"base64url").toString("utf8"));}
export function createPkce(){const verifier=randomBytes(48).toString("base64url");const challenge=createHash("sha256").update(verifier).digest("base64url");return {verifier,challenge,method:"S256" as const};}
function getJson<T>(url:string):Promise<T>{return new Promise((resolve,reject)=>{const req=httpsGet(url,{timeout:3000,headers:{accept:"application/json"}},res=>{if((res.statusCode??500)>=400){res.resume();reject(new Error("OIDC HTTP error"));return;}const chunks:Buffer[]=[];res.on("data",chunk=>chunks.push(Buffer.from(chunk)));res.on("end",()=>{try{resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")) as T);}catch(e){reject(e);}});});req.on("timeout",()=>req.destroy(new Error("OIDC request timed out")));req.on("error",reject);});}
export async function verifyOidcJwt(token:string):Promise<AuthContext>{
  const issuer=(process.env.OIDC_ISSUER_URL??"").replace(/\/$/,""); const audience=process.env.OIDC_AUDIENCE??"verideploy-api";
  if(!issuer) throw new Error("OIDC_ISSUER_URL is required");
  const parts=token.split("."); if(parts.length!==3) throw new Error("invalid JWT");
  const header=b64urlJson(parts[0]!); const claims=b64urlJson(parts[1]!);
  if(header.alg!=="RS256") throw new Error("unsupported token algorithm");
  const discovery=await getJson<{jwks_uri:string}>(`${issuer}/.well-known/openid-configuration`);
  if(!discovery.jwks_uri.startsWith("https://"))throw new Error("JWKS URI must use HTTPS");
  const jwks=await getJson<{keys:Jwk[]}>(discovery.jwks_uri);
  const jwk=jwks.keys.find(k=>k.kid===header.kid&&k.kty==="RSA"); if(!jwk) throw new Error("signing key not found");
  const key=createPublicKey({key:jwk as any,format:"jwk"}); const ok=verify("RSA-SHA256",Buffer.from(`${parts[0]}.${parts[1]}`),key,Buffer.from(parts[2]!,"base64url")); if(!ok)throw new Error("invalid token signature");
  const now=Math.floor(Date.now()/1000); const aud=Array.isArray(claims.aud)?claims.aud:[claims.aud];
  if(claims.iss!==issuer||!aud.includes(audience)||Number(claims.exp)<=now-60||Number(claims.iat)>now+60) throw new Error("invalid token claims");
  if(typeof claims.sub!=="string"||typeof claims.tenant_id!=="string"||!Array.isArray(claims.roles))throw new Error("required identity claims missing");
  return {subject:claims.sub,tenantId:claims.tenant_id,roles:claims.roles.filter((r:unknown)=>typeof r==="string"),attributes:typeof claims.attributes==="object"&&claims.attributes?claims.attributes:{}};
}
