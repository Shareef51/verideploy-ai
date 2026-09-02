export type AppEnvironment="development"|"test"|"staging"|"production";
export type GatewayConfig={env:AppEnvironment;port:number;aiServiceBaseUrl:string;redisUrl:string;kafkaBrokers:string[];oidcIssuerUrl:string;oidcAudience:string;corsOrigins:string[]};
function required(name:string,env:NodeJS.ProcessEnv){const value=env[name]?.trim();if(!value)throw new Error(`Missing required configuration: ${name}`);return value;}
function integer(name:string,value:string|undefined,fallback:number){const n=value?Number(value):fallback;if(!Number.isInteger(n)||n<1||n>65535)throw new Error(`Invalid integer configuration: ${name}`);return n;}
export function loadGatewayConfig(env:NodeJS.ProcessEnv=process.env):GatewayConfig{
 const appEnv=(env.APP_ENV??"development") as AppEnvironment;if(!["development","test","staging","production"].includes(appEnv))throw new Error("Invalid APP_ENV");
 const strict=appEnv==="staging"||appEnv==="production";
 const cfg={env:appEnv,port:integer("PORT",env.PORT,4000),aiServiceBaseUrl:strict?required("AI_SERVICE_BASE_URL",env):(env.AI_SERVICE_BASE_URL??"http://ai-service:8000"),redisUrl:strict?required("REDIS_URL",env):(env.REDIS_URL??"redis://redis:6379/0"),kafkaBrokers:(strict?required("KAFKA_BROKERS",env):(env.KAFKA_BROKERS??"kafka:9092")).split(",").map(v=>v.trim()).filter(Boolean),oidcIssuerUrl:strict?required("OIDC_ISSUER_URL",env):(env.OIDC_ISSUER_URL??""),oidcAudience:env.OIDC_AUDIENCE??"verideploy-api",corsOrigins:(env.CORS_ALLOWED_ORIGINS??env.WEB_BASE_URL??"http://localhost:3000").split(",").map(v=>v.trim()).filter(Boolean)};
 if(appEnv==="production"&&cfg.oidcIssuerUrl&&!cfg.oidcIssuerUrl.startsWith("https://"))throw new Error("Production OIDC issuer must use HTTPS");return Object.freeze(cfg);
}
export const SECRET_ENV_NAMES=Object.freeze(["APP_SECRET_KEY","FRONTEND_SESSION_SECRET","OIDC_CLIENT_SECRET","INTERNAL_SERVICE_AUTH_SECRET","OPENAI_API_KEY","S3_ACCESS_KEY","S3_SECRET_KEY","GITHUB_API_TOKEN","JIRA_API_TOKEN","RUNTIME_OBSERVABILITY_TOKEN","LANGSMITH_API_KEY","CACHE_ENCRYPTION_SECRET","APPROVAL_SIGNING_SECRET"] as const);
export function redactConfig(record:Record<string,unknown>){return Object.fromEntries(Object.entries(record).map(([k,v])=>[k,SECRET_ENV_NAMES.some(s=>s.toLowerCase()===k.toLowerCase())?"[REDACTED]":v]));}
