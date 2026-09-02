import { Injectable, NestMiddleware, UnauthorizedException } from "@nestjs/common";
import type { NextFunction, Request, Response } from "express";
import { verifyOidcJwt } from "./oidc";

@Injectable()
export class AuthContextMiddleware implements NestMiddleware{
  async use(req:Request,res:Response,next:NextFunction){
    if(req.path.endsWith("/health/live")||req.path.endsWith("/health/ready"))return next();
    if(process.env.GATEWAY_DEV_AUTH_BYPASS==="true"&&process.env.NODE_ENV!=="production"){
      req.headers["x-user-id"]=process.env.GATEWAY_DEV_USER_ID??"22222222-2222-4222-8222-222222222222";
      req.headers["x-tenant-id"]=process.env.GATEWAY_DEV_TENANT_ID??"11111111-1111-4111-8111-111111111111";
      req.headers["x-auth-roles"]="developer"; return next();
    }
    const auth=req.headers.authorization??""; if(!auth.startsWith("Bearer "))throw new UnauthorizedException("bearer token required");
    try{const ctx=await verifyOidcJwt(auth.slice(7));req.headers["x-user-id"]=ctx.subject;req.headers["x-tenant-id"]=ctx.tenantId;req.headers["x-auth-roles"]=ctx.roles.join(",");return next();}
    catch{throw new UnauthorizedException("invalid bearer token");}
  }
}
