import { Injectable, NestMiddleware } from "@nestjs/common";
import type { NextFunction, Request, Response } from "express";

@Injectable()
export class SecurityHeadersMiddleware implements NestMiddleware{
  use(req:Request,res:Response,next:NextFunction){
    const origin=req.headers.origin; const allowed=(process.env.CORS_ALLOWED_ORIGINS??"http://localhost:3000").split(",").map(v=>v.trim()).filter(Boolean);
    if(origin&&allowed.includes(origin)){res.setHeader("Access-Control-Allow-Origin",origin);res.setHeader("Vary","Origin");res.setHeader("Access-Control-Allow-Credentials","true");}
    res.setHeader("Content-Security-Policy",process.env.CONTENT_SECURITY_POLICY??"default-src 'none'; frame-ancestors 'none'; base-uri 'none'");
    res.setHeader("X-Content-Type-Options","nosniff");res.setHeader("Referrer-Policy","no-referrer");res.setHeader("Permissions-Policy","camera=(), microphone=(), geolocation=()");res.setHeader("Cross-Origin-Opener-Policy","same-origin");
    if(process.env.NODE_ENV==="production")res.setHeader("Strict-Transport-Security","max-age=31536000; includeSubDomains");
    if(["POST","PUT","PATCH","DELETE"].includes(req.method)&&req.headers.cookie&&origin&&!allowed.includes(origin)){res.status(403).json({error:{code:"CSRF_ORIGIN_REJECTED",message:"request origin is not allowed"}});return;}
    if(req.method==="OPTIONS"){res.setHeader("Access-Control-Allow-Methods","GET,POST,PUT,PATCH,DELETE,OPTIONS");res.setHeader("Access-Control-Allow-Headers","Authorization,Content-Type,Idempotency-Key,X-Correlation-Id");res.status(204).end();return;}
    next();
  }
}
